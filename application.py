import os
from flask import Flask
from flask import render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

application = app = Flask(__name__)

# https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/using-features.managing.db.html?icmpid=docs_elasticbeanstalk_console
db_username = os.environ["RDS_USERNAME"]
db_password = os.environ["RDS_PASSWORD"]
db_host     = os.environ["RDS_HOSTNAME"]
db_port     = int(os.environ["RDS_PORT"])
db_name     = os.environ["RDS_DB_NAME"]

# app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///hello.sqlite"
app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql://{db_username}:{db_password}@{db_host}:{db_port}/{db_name}"
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"

@app.route("/t")
@app.route("/t/<varName>")
def show_template(varName=None):
    dbError = None
    if varName:
        try:
            db.session.add(User(name=varName))
            db.session.commit()
        except IntegrityError as err:
            print(f"Crap... {err}")
            dbError = err
            db.session.rollback()

    rowCount = db.session.query(User).count()

    return render_template('test.html', varName=varName, nameCount=rowCount, dbError=dbError)

with app.app_context():
    db.create_all()

    # db.session.add(User(name="test2"))
    # db.session.commit()

    # users = db.session.execute(db.select(User)).scalars()