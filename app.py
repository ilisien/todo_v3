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

def move_task(upordown,):


@app.route('/')
def base_view():
    # Get all root tasks (tasks without parent)
    root_tasks = Task.query.filter_by(parent_id=None).all()
    return render_template("todo.html", tasks=root_tasks)

@app.route("/create-first-task", methods=["POST"])
def create_first_task():
    # Create first root task
    how_many_other_roots = len(Task.query.filter_by(parent_id=None).all())
    new_task = Task(name="",order=how_many_other_roots)
    db.session.add(new_task)
    db.session.commit()
    
    # Return the new task wrapped in the task list
    root_tasks = Task.query.filter_by(parent_id=None).all()
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

@app.route("/update-task/<int:task_id>", methods=["POST"])
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    task.name = request.form.get('name', '')
    db.session.commit()
    
    # Return the updated task
    return render_template("_task_content.html", task=task)

@app.route("/delete-task/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()

    return ""

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)