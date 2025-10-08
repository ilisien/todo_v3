import datetime, time, secrets, os

from flask import Flask, redirect, url_for, request, render_template, session, redirect, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.security import check_password_hash
from password_hash import PASSWORD_HASH

app = Flask(__name__)
app.secret_key = "secret key"
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'backend.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

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
    due_date = db.Column(db.DateTime, default=datetime.datetime.now)


def displace_task(displacement,task_id,task_new_pos=None):
    task_at_hand = Task.query.get_or_404(task_id)
    task_start_pos = task_at_hand.order
    if task_new_pos is None:
        task_new_pos = task_start_pos + displacement
    siblings_of_task = sorted(Task.query.filter_by(parent_id=task_at_hand.parent_id).all(),key=lambda x: x.order)
    if 0 <= task_new_pos <= len(siblings_of_task)-1:
        siblings_of_task.insert(task_new_pos,siblings_of_task.pop(task_start_pos))
        
        for i, sibling in enumerate(siblings_of_task):
            sibling.order = i
        
        db.session.commit()

def get_correct_root_tasks():
    if not session['show_completed_tasks']:
        root_tasks = attach_other_classes(get_incomplete_task_tree())
    else:
        root_tasks = attach_other_classes(sorted(Task.query.filter_by(parent_id=None).all(),key=lambda x: x.order))
    return root_tasks

def get_incomplete_task_tree():
    root_tasks = Task.query.filter_by(parent_id=None, completed=False).order_by(Task.order).all()
    
    def filter_children(task):
        task.children = [filter_children(child) for child in task.children if not child.completed]
        return task

    return [filter_children(task) for task in root_tasks]

def attach_other_classes(tasks):
    for task in tasks:
        task.other_classes = get_updated_date_warning(task.id)
        for child in getattr(task, 'children', []):
            attach_other_classes([child])
    return tasks

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
    # Get all root tasks (tasks without parent)
    session['show_completed_tasks'] = True
    try:
        root_tasks = attach_other_classes(sorted(Task.query.filter_by(parent_id=None).all(),key=lambda x: x.order))
    except Exception as e:
        return f"there was an error with getting initial tasks: {e}"
    return render_template("todo.html", tasks=root_tasks)

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
    
    return render_template("_task.html", task=attach_other_classes([new_task])[0])

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
    
    # Return the updated task
    return task.name

@app.route("/update-task-description/<int:task_id>", methods=["POST"])
def update_task_description(task_id):
    task = Task.query.get_or_404(task_id)
    task.description = request.form.get('description', '')
    db.session.commit()
    
    # Return the updated task
    return task.description

@app.route("/refresh/<string:to_refresh>/<int:task_id>", methods=["POST"])
def refresh(to_refresh,task_id):
    time.sleep(0.5)
    task = Task.query.get_or_404(task_id)
    if to_refresh == "date":
        other_classes = get_updated_date_warning(task_id)
        return render_template("_due_wrapper.html",other_classes=other_classes, task=task)
    if to_refresh == "complete":
        task = Task.query.get_or_404(task_id)
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
    displace_task(int(request.form.get('displacement', '')),task_id)
    
    # This probably doesn't require a full re-render, but i'm not ready to figure out how to not to this yet
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
        today = datetime.datetime.now().date()
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

@app.route("/toggle-completed-tasks/",methods=["POST"])
def toggle_completed_tasks():
    session['show_completed_tasks'] = not session['show_completed_tasks']
    root_tasks=get_correct_root_tasks()
    return render_template("_task_list.html", tasks=root_tasks, )

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True,host='0.0.0.0') #,host='0.0.0.0'
