import os
import datetime, time

from flask import Flask, redirect, url_for, request, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


app = Flask(__name__)
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
    name = db.Column(db.String(512), nullable=False, default="")
    description = db.Column(db.String(2048), default="")
    due_date = db.Column(db.DateTime, default=datetime.datetime.now)

def displace_task(displacement,task_id):
    task_at_hand = Task.query.get_or_404(task_id)
    task_start_pos = task_at_hand.order
    task_new_pos = task_start_pos + displacement
    siblings_of_task = sorted(Task.query.filter_by(parent_id=task_at_hand.parent_id).all(),key=lambda x: x.order)
    if 0 <= task_new_pos <= len(siblings_of_task)-1:
        siblings_of_task.insert(task_new_pos,siblings_of_task.pop(task_start_pos))
        
        for i, sibling in enumerate(siblings_of_task):
            sibling.order = i
        
        db.session.commit()

@app.route('/')
def base_view():
    # Get all root tasks (tasks without parent)
    root_tasks = sorted(Task.query.filter_by(parent_id=None).all(),key=lambda x: x.order)
    return render_template("todo.html", tasks=root_tasks)

@app.route("/create-first-task", methods=["POST"])
def create_first_task():
    # Create first root task
    how_many_other_roots = len(Task.query.filter_by(parent_id=None).all())
    new_task = Task(name="",order=how_many_other_roots)
    db.session.add(new_task)
    db.session.commit()
    
    # Return the new task wrapped in the task list
    root_tasks = sorted(Task.query.filter_by(parent_id=None).all(),key=lambda x: x.order)
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
    
    # Return the updated task
    return task.name

@app.route("/move-task/<int:task_id>", methods=["POST"])
def move_task(task_id):
    displace_task(int(request.form.get('displacement', '')),task_id)
    
    # This probably doesn't require a full re-render, but i'm not ready to figure out how to not to this yet
    root_tasks = sorted(Task.query.filter_by(parent_id=None).all(),key=lambda x: x.order)
    return render_template("_task_list.html", tasks=root_tasks)

@app.route("/update-task-due/<string:date_part>/<int:task_id>", methods=["POST"])
def update_task_due(date_part,task_id):
    print(date_part,task_id)
    task = Task.query.get_or_404(task_id)
    if date_part == "day":
        try:
            task.due_date = task.due_date.replace(day=int(request.form.get('day','')))
            db.session.commit()
            return task.due_date.strftime('%#d')
        except:
            return task.due_date.strftime('%#d')

    elif date_part == "month":
        try:
            task.due_date = task.due_date.replace(month=int(request.form.get('month','')))
            db.session.commit()
            return task.due_date.strftime('%#m')
        except:
            return task.due_date.strftime('%#m')

    elif date_part == "year":
        try:
            task.due_date = task.due_date.replace(year=int(f"202{request.form.get('year','')}"))
            db.session.commit()
            return str(task.due_date.year)[-1]
        except:
            return str(task.due_date.year)[-1]

@app.route("/delete-task/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()

    return ""

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True) #,host='0.0.0.0'