from flask import Flask
from flask import render_template
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///hello.sqlite"
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, nullable=False)

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"

@app.route("/t")
@app.route("/t/<varName>")
def show_template(varName=None):
    return render_template('test.html', varName=varName)

with app.app_context():
    db.create_all()

    db.session.add(User(name="test2"))
    db.session.commit()

    users = db.session.execute(db.select(User)).scalars()