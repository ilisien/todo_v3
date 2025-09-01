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

@app.route('/')
def base_view():
    return render_template("todo.html")

class Task(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer,db.ForeignKey("tasks.id"))
    children = db.relationship("Task", back_populates="parent")
    parent = db.relationship("Task", back_populates="children", remote_side=[id])

    name = db.Column(db.String(512),nullable=True)
    description = db.Column(db.String(2048),default="")
    due_date = db.Column(db.DateTime,default=datetime.datetime.now)

@app.route("/create-first-task", methods=["POST"])
def update_text():
    time.sleep(1)
    return render_template("task.html")

if __name__ == "__main__":
    app.run(debug=True)