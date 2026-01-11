import datetime, time, secrets, os
from pytz import timezone

from flask import Flask, redirect, url_for, request, render_template, session, redirect, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.security import check_password_hash
from config import PASSWORD_HASH
from config import SECRET_KEY
from flask_migrate import Migrate

app = Flask(__name__)
app.secret_key = SECRET_KEY
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'backend.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)
TZ = timezone('EST')

@app.after_request
def suffixes(response):
    if session.get("authenticated"):
        state = AppState.query.first()
        if not state:
            state = AppState()
            db.session.add(state)
        state.last_checked_in = datetime.datetime.now(TZ)
        db.session.commit()
        print(f"last_checked_in at: {state.last_checked_in}")
    return response

class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    order = db.Column(db.Integer, default=0)
    parent_id = db.Column(db.Integer, db.ForeignKey("tasks.id"))
    children = db.relationship("Task", cascade="all, delete-orphan",back_populates="parent",order_by="Task.order")
    parent = db.relationship("Task", back_populates="children", remote_side=[id])

    completed = db.Column(db.Boolean, default=False)
    show_as_task = db.Column(db.Boolean, default=True)
    show_date = db.Column(db.Boolean, default=False)

    name = db.Column(db.String(512), nullable=False, default="")
    description = db.Column(db.String(2048), default="")
    tags = db.Column(db.String(512), default="")
    schedule = db.Column(db.String(512), default="")
    due_date = db.Column(db.DateTime, default=datetime.datetime.now(TZ))

    def get_tags(self):
        """Return list of tags"""
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
    
    def set_tags(self, tags_list):
        """Set tags from a list"""
        if isinstance(tags_list, str):
            # If string, clean it up
            tags_list = [tag.strip() for tag in tags_list.split(',') if tag.strip()]
        self.tags = ', '.join(tags_list)
    
    def get_tags_display(self):
        """Return tags as display string"""
        return self.tags if self.tags else ""

    def get_due_classes(self):
        classes = "due-wrapper "
        if self.show_date:
            today = datetime.datetime.now(TZ).date()
            if self.due_date.date() < today:
                classes += "past-due "
            elif self.due_date.date() == today:
                classes += "due-today "
            elif self.due_date.date() == today + datetime.timedelta(days=1):
                classes += "due-tomorrow "
            elif self.due_date.date() <= today + datetime.timedelta(days=7):
                classes += "due-this-week "
            return classes
        else:
            classes += "hidden "
            return classes

class AppState(db.Model):
    __tablename__ = "app_state"
    
    id = db.Column(db.Integer, primary_key=True)
    show_completed = db.Column(db.Boolean, default=True)
    active_tags = db.Column(db.String(1024), default="")  # comma-separated list of active tags
    last_checked_in = db.Column(db.DateTime, default=datetime.datetime.now(TZ))
    
    def get_active_tags(self):
        if not self.active_tags:
            return []
        return [tag.strip() for tag in self.active_tags.split(',') if tag.strip()]
    
    def set_active_tags(self, tags_list):
        """Set active tags from a list"""
        if isinstance(tags_list, list):
            self.active_tags = ','.join(tags_list)
        else:
            self.active_tags = tags_list

def children(parent_id):
    return sorted(
            Task.query.filter_by(parent_id=parent_id).all(),
            key=lambda x: x.order)

def get_default_filters():
    return {
        'show_completed': True,
        'active_tags': ""  # Store as empty string, not list
    }

def load_filters():
    state = AppState.query.first()
    if not state:
        # Create default state
        defaults = get_default_filters()
        state = AppState(
            show_completed=defaults['show_completed'],
            active_tags=defaults['active_tags']
        )
        db.session.add(state)
        db.session.commit()
    
    return {
        'show_completed': state.show_completed,
        'active_tags': state.get_active_tags()
    }


def save_filters(show_completed=None, active_tags=None):
    state = AppState.query.first()
    if not state:
        state = AppState()
        db.session.add(state)
    
    if show_completed is not None:
        state.show_completed = show_completed
    
    if active_tags is not None:
        state.set_active_tags(active_tags)
    
    db.session.commit()


def get_all_tags():
    all_tasks = Task.query.all()
    tags = set()
    for task in all_tasks:
        tags.update(task.get_tags())
    return sorted(list(tags))


def apply_filters(tasks, filters):
    active_tags = filters.get('active_tags', [])
    show_completed = filters.get('show_completed', True)

    # First, apply completion filtering if needed
    if not show_completed:
        def filter_completed(task):
            task.children = [filter_completed(child) for child in task.children if not child.completed]
            return task
        
        tasks = [task for task in tasks if not task.completed]
        tasks = [filter_completed(task) for task in tasks]
    
    # Then, apply tag filtering
    if active_tags:
        def filter_by_tags(task, parent_matched=False):
            task_tags = task.get_tags()
            task_matches = any(tag in active_tags for tag in task_tags)
            
            if parent_matched or task_matches:
                # This task should be shown - keep ALL its children
                return task
            else:
                # This task doesn't match - check if any children match
                # If children match, they get promoted
                matching_children = []
                for child in task.children:
                    filtered = filter_by_tags(child, parent_matched=False)
                    if filtered:
                        matching_children.append(filtered)
                
                # Don't show this task, but return its matching children to be promoted
                return matching_children if matching_children else None
        
        filtered_tasks = []
        for task in tasks:
            result = filter_by_tags(task, parent_matched=False)
            if result:
                if isinstance(result, list):
                    # Children were promoted
                    filtered_tasks.extend(result)
                else:
                    # Task itself matched
                    filtered_tasks.append(result)
        
        return filtered_tasks
    
    return tasks

def apply_scheduling(tasks):
    state = AppState.query.first()
    if not state:
        state = AppState()
        db.session.add(state)

    last_checked_in = state.last_checked_in.strftime('%A').lower()
    today = datetime.datetime.now(TZ).strftime('%A').lower()

    if last_checked_in != today:
        def uncomplete_scheduled(task):
            #(and vice versa)
            schedule = [t.strip() for t in task.schedule.lower().split(',') if t.strip() != ""]

            if len(schedule) > 0:
                if 'daily' in schedule:
                    task.completed = False
                elif today in schedule:
                    task.completed = False
                elif today not in schedule:
                    task.completed = True
            
            for child in task.children:
                uncomplete_scheduled(child)
        
        for task in tasks:
            uncomplete_scheduled(task)
    
    db.session.commit()
    return tasks

def displace_task(displacement,task_id,task_new_pos=None):
    task_at_hand = Task.query.get_or_404(task_id)
    
    siblings_of_task = sorted(
        Task.query.filter_by(parent_id=task_at_hand.parent_id).all(),
        key=lambda x: x.order
    )
    
    task_start_pos = next(i for i, t in enumerate(siblings_of_task) if t.id == task_id)
    
    if task_new_pos is None:
        task_new_pos = task_start_pos + displacement
    
    if 0 <= task_new_pos <= len(siblings_of_task) - 1:
        siblings_of_task.insert(task_new_pos, siblings_of_task.pop(task_start_pos))
        
        for i, sibling in enumerate(siblings_of_task):
            sibling.order = i
        
        db.session.commit()


def dent_task_to_parent(task_id, new_parent_id):
    task = Task.query.get_or_404(task_id)
    new_parent = Task.query.get_or_404(new_parent_id)
    
    # Get old siblings before changing parent
    old_siblings = children(task.parent_id)
    
    # Change parent
    task.parent_id = new_parent_id
    
    # Get new siblings and add task at the beginning
    new_siblings = children(new_parent_id)
    
    # Renumber old siblings (task is no longer among them)
    for i, sibling in enumerate(old_siblings):
        sibling.order = i
    
    # Renumber new siblings (task is now first)
    for i, sibling in enumerate(new_siblings):
        sibling.order = i
    
    db.session.commit()


def dent_task(displacement, task_id):
    task_at_hand = Task.query.get_or_404(task_id)

    if displacement < 0:  # OUTDENT
        if task_at_hand.parent_id == None:
            return
        
        parent_of_task = Task.query.get_or_404(task_at_hand.parent_id)
        
        aunts_and_uncles = children(parent_of_task.parent_id)

        parent_start_position = next(i for i, t in enumerate(aunts_and_uncles) if t.id == task_at_hand.parent_id)

        task_at_hand.parent_id = parent_of_task.parent_id

        aunts_and_uncles.insert(parent_start_position + 1, task_at_hand)

        for i, sibling in enumerate(aunts_and_uncles):
            sibling.order = i

        old_siblings = children(parent_of_task.id)

        for i, sibling in enumerate(old_siblings):
            sibling.order = i

        db.session.commit()

    elif displacement > 0:  # INDENT
        siblings = children(task_at_hand.parent_id)

        task_start_position = next(i for i, t in enumerate(siblings) if t.id == task_id)

        if task_start_position == 0:
            return

        new_parent = siblings[task_start_position - 1]

        new_siblings = children(new_parent.id)

        task_at_hand.parent_id = new_parent.id

        new_siblings.insert(0, task_at_hand)

        for i, sibling in enumerate(new_siblings):
            sibling.order = i

        old_siblings = children(new_parent.parent_id)

        for i, sibling in enumerate(old_siblings):
            sibling.order = i

        db.session.commit()

def get_correct_root_tasks():
    filters = load_filters()
    root_tasks = sorted(Task.query.filter_by(parent_id=None).all(), key=lambda x: x.order)
    root_tasks = apply_scheduling(root_tasks)
    return apply_filters(root_tasks, filters)

@app.before_request
def require_login():
    if request.endpoint not in ("login", "static"):
        if not session.get("authenticated"):
            if request.headers.get("HX-Request"):
                resp = Response("", status=200)
                resp.headers["HX-Redirect"] = url_for("login")
                return resp
            return redirect(url_for("login"))

@app.route('/')
def base_view():
    try:
        filters = load_filters()
        root_tasks = get_correct_root_tasks()
        all_tags = get_all_tags()
        
        return render_template("todo.html", 
                             tasks=root_tasks, 
                             all_tags=all_tags,
                             filters=filters)
    except Exception as e:
        return f"there was an error with getting initial tasks: {e}"


@app.route('/login', methods=["GET","POST"])
def login():
    if request.method == "POST":
        if check_password_hash(PASSWORD_HASH, request.form["password"]):
            session["authenticated"] = True
            return redirect(url_for("base_view"))
        else:
            return render_template("login.html", error="nope. try again")
    return render_template("login.html")


@app.route('/logout')
def logout():
    session.clear()
    return redirect("/login")


@app.route("/create-first-task/<int:position>", methods=["POST"])
def create_first_task(position):
    # Create first root task
    how_many_other_roots = len(Task.query.filter_by(parent_id=None).all())
    new_task = Task(name="",order=how_many_other_roots)
    db.session.add(new_task)
    db.session.commit()
    if position == 0:
        displace_task(None,new_task.id,0)
    
    # Return the new task wrapped in the task list
    root_tasks = get_correct_root_tasks()
    return render_template("_task_list.html", tasks=root_tasks)


@app.route("/create-subtask/<int:parent_id>", methods=["POST"])
def create_subtask(parent_id):
    # Create new subtask
    how_many_siblings = len(Task.query.filter_by(parent_id=parent_id).all())
    new_task = Task(name="", parent_id=parent_id,order=how_many_siblings)
    db.session.add(new_task)
    db.session.commit()
    
    return render_template("_task.html", task=new_task)


@app.route("/toggle-task/<int:task_id>", methods=["POST"])
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    task.completed = not task.completed
    db.session.commit()
    
    # Return the updated task content
    return render_template("_task_content.html", task=task)


@app.route("/update-task-name/<int:task_id>", methods=["POST"])
def update_task_name(task_id):
    task = Task.query.get_or_404(task_id)
    task.name = request.form.get('name', '')
    db.session.commit()
    
    return task.name


@app.route("/update-task-description/<int:task_id>", methods=["POST"])
def update_task_description(task_id):
    task = Task.query.get_or_404(task_id)
    task.description = request.form.get('description', '')
    db.session.commit()
    
    return task.description


@app.route("/update-task-tags/<int:task_id>", methods=["POST"])
def update_task_tags(task_id):
    """Update task tags"""
    task = Task.query.get_or_404(task_id)
    tags_string = request.form.get('tags', '')
    task.set_tags(tags_string)
    db.session.commit()
    
    return task.get_tags_display()

@app.route("/update-task-schedule/<int:task_id>",methods=["POST"])
def update_task_schedule(task_id):
    task = Task.query.get_or_404(task_id)
    schedule_string = request.form.get('schedule','')
    task.schedule = schedule_string

    state = AppState.query.first()
    if not state:
        state = AppState()
        db.session.add(state)
    
    last_checked_in = state.last_checked_in.strftime('%A').lower()
    today = datetime.datetime.now(TZ).strftime('%A').lower()

    schedule = [t.strip() for t in task.schedule.lower().split(',') if t.strip() != ""]
    if len(schedule) > 0:
        if (not today in schedule) and (not 'daily' in schedule):
            task.completed = True

    db.session.commit()

    root_tasks = get_correct_root_tasks()
    return render_template("_completed.html", task=task)

@app.route("/refresh/<string:to_refresh>/<int:task_id>", methods=["POST"])
def refresh(to_refresh,task_id):
    time.sleep(0.5)
    task = Task.query.get_or_404(task_id)
    if to_refresh == "date":
        return render_template("_due_wrapper.html", task=task)
    if to_refresh == "complete":
        return render_template("_completed.html", task=task)


@app.route("/update-task-option/<string:option>/<int:task_id>", methods=["POST"])
def update_task_option(option,task_id):
    task = Task.query.get_or_404(task_id)
    if option == "show-date-toggle":
        task.show_date = not task.show_date
        if task.show_date:
            return_string = "[x] showing due date"
        else:
            return_string = "[ ] hiding due date"
    elif option == "show-as-task-toggle":
        task.show_as_task = not task.show_as_task
        if task.show_as_task:
            return_string = "[x] showing as task"
        else:
            return_string = "[ ] showing as list item"
    db.session.commit()
    return return_string


@app.route("/move-task/<int:task_id>", methods=["POST"])
def move_task(task_id):
    displacement = int(request.form.get('displacement', ''))
    
    # Get current filters
    filters = load_filters()
    
    # Get the task being moved
    task = Task.query.get_or_404(task_id)
    
    # Get all siblings
    all_siblings = sorted(
        Task.query.filter_by(parent_id=task.parent_id).all(),
        key=lambda x: x.order
    )
    
    visible_siblings = apply_filters(all_siblings, filters)
    
    visible_ids = [t.id for t in visible_siblings]
    if task_id not in visible_ids:
        root_tasks = get_correct_root_tasks()
        return render_template("_task_list.html", tasks=root_tasks)
    
    current_visible_pos = visible_ids.index(task_id)
    new_visible_pos = current_visible_pos + displacement
    
    new_visible_pos = max(0, min(new_visible_pos, len(visible_siblings) - 1))
    
    target_task = visible_siblings[new_visible_pos]
    
    target_full_pos = next(i for i, t in enumerate(all_siblings) if t.id == target_task.id)
    
    displace_task(None, task_id, target_full_pos)
    
    root_tasks = get_correct_root_tasks()
    return render_template("_task_list.html", tasks=root_tasks)

@app.route("/climb-task/<int:task_id>", methods=["POST"])
def climb_task(task_id):
    displacement = int(request.form.get('displacement', ''))
    
    # Get current filters
    filters = load_filters()
    
    # Get the task being moved
    task = Task.query.get_or_404(task_id)
    
    if displacement < 0:  # OUTDENT
        # Can't outdent if already at root
        if task.parent_id is None:
            root_tasks = get_correct_root_tasks()
            return render_template("_task_list.html", tasks=root_tasks)
        
        # We want to outdent, so just call the original function
        dent_task(displacement, task_id)
    
    elif displacement > 0:  # INDENT
        # Get all siblings (same parent)
        all_siblings = sorted(
            Task.query.filter_by(parent_id=task.parent_id).all(),
            key=lambda x: x.order
        )
        
        # Apply filters to get visible siblings
        visible_siblings = apply_filters(all_siblings, filters)
        
        # Find task's position in visible list
        visible_ids = [t.id for t in visible_siblings]
        if task_id not in visible_ids:
            root_tasks = get_correct_root_tasks()
            return render_template("_task_list.html", tasks=root_tasks)
        
        current_visible_pos = visible_ids.index(task_id)
        
        # Can't indent if it's the first visible item (nothing to indent under)
        if current_visible_pos == 0:
            root_tasks = get_correct_root_tasks()
            return render_template("_task_list.html", tasks=root_tasks)
        
        # Get the visible sibling immediately before this one
        new_parent = visible_siblings[current_visible_pos - 1]
        
        # Now perform the indent operation to make it a child of new_parent
        dent_task_to_parent(task_id, new_parent.id)
    
    root_tasks = get_correct_root_tasks()
    return render_template("_task_list.html", tasks=root_tasks)

@app.route("/update-task-due/<string:date_part>/<int:task_id>", methods=["POST"])
def update_task_due(date_part,task_id):
    task = Task.query.get_or_404(task_id)
    if date_part == "day":
        try:
            task.due_date = task.due_date.replace(day=int(request.form.get('day','')))
            db.session.commit()
        except:
            pass
        return task.due_date.strftime('%d')

    elif date_part == "month":
        try:
            task.due_date = task.due_date.replace(month=int(request.form.get('month','')))
            db.session.commit()
        except:
            pass
        return task.due_date.strftime('%m')

    elif date_part == "year":
        try:
            task.due_date = task.due_date.replace(year=int(f"202{request.form.get('year','')}"))
            db.session.commit()
        except:
            pass
        return str(task.due_date.year)[-1]


@app.route("/get-updated-date-warning/<int:task_id>/", methods=["POST"])
def get_updated_date_warning(task_id):
    task = Task.query.get_or_404(task_id)

    other_classes = "due-wrapper "
    if task.show_date:
        today = datetime.datetime.now(TZ).date()
        if task.due_date.date() < today:
            other_classes += "past-due "
        elif task.due_date.date() == today:
            other_classes += "due-today "
        elif task.due_date.date() == today + datetime.timedelta(days=1):
            other_classes += "due-tomorrow "
        elif (task.due_date.date() <= today + datetime.timedelta(days=7)):
            other_classes += "due-this-week "
        return other_classes
    else:
        other_classes += "hidden "
        return other_classes


@app.route("/delete-task/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()

    return ""


@app.route("/set-filter/<filter_type>/<filter_value>", methods=["POST"])
def set_filter(filter_type, filter_value):
    """Update filter state and return updated content"""
    filters = load_filters()
    
    if filter_type == "completed":
        # Toggle completed filter
        new_value = filter_value.lower() == "true"
        save_filters(show_completed=new_value)
        filters['show_completed'] = new_value
    
    elif filter_type == "tag":
        # Toggle tag filter
        active_tags = filters['active_tags']
        if filter_value == "all":
            # Clear all tag filters
            active_tags = []
        elif filter_value in active_tags:
            # Remove tag from filters
            active_tags.remove(filter_value)
        else:
            # Add tag to filters
            active_tags.append(filter_value)
        
        save_filters(active_tags=active_tags)
        filters['active_tags'] = active_tags
    
    # Return both tabs and task list
    root_tasks = get_correct_root_tasks()
    all_tags = get_all_tags()
    
    print(f"Filter changed: {filter_type}={filter_value}")
    print(f"Active tags: {filters['active_tags']}")
    print(f"Show completed: {filters['show_completed']}")
    print(f"Returning {len(root_tasks)} tasks")
    
    return render_template("_main_content.html", 
                         tasks=root_tasks, 
                         all_tags=all_tags,
                         filters=filters)


@app.route("/refresh-tabs", methods=["POST"])
def refresh_tabs():
    """Return just the filter tabs (for after tag edits)"""
    filters = load_filters()
    all_tags = get_all_tags()
    
    return render_template("_filter_tabs.html", 
                         all_tags=all_tags,
                         filters=filters)


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True,host='0.0.0.0')