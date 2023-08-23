from __future__ import annotations
import os
from flask import Flask
from flask import render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

from typing import List

from sqlalchemy import ForeignKey
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import relationship

import datetime
import pdb

application = app = Flask(__name__)

# https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/using-features.managing.db.html?icmpid=docs_elasticbeanstalk_console
db_username = os.environ["RDS_USERNAME"]
db_password = os.environ["RDS_PASSWORD"]
db_host     = os.environ["RDS_HOSTNAME"]
db_port     = int(os.environ["RDS_PORT"])
db_name     = os.environ["RDS_DB_NAME"]

#app.config["MYSQL_CURSORCLASS"] = "DictCursor"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///dbtest.sqlite"
# app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql://{db_username}:{db_password}@{db_host}:{db_port}/{db_name}"
db = SQLAlchemy(app)

class Base(DeclarativeBase):
    pass

class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    accessID: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(unique=True)
    grade: Mapped[int]
    teacher: Mapped[str]

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    startDate: Mapped[datetime.date]
    endDate: Mapped[datetime.date]
    active: Mapped[bool]
    electives: Mapped[List["Elective"]] = relationship(back_populates="session")

class Elective(Base):
    __tablename__ = "electives"
    id: Mapped[int] = mapped_column(primary_key=True)
    sessionID: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    session: Mapped["Session"] = relationship(back_populates="electives")
    name: Mapped[str]
    lead: Mapped[str]
    maxAttendees: Mapped[int]
    day: Mapped[str]
    rotation: Mapped[int]
    multisession: Mapped[bool]
    room: Mapped[str]
    consideredPE: Mapped[bool]

@app.route("/")
def hello_world():
    result = db.session.execute(db.select(Elective)).scalars()
    return "<p>{result}</p>"

with app.app_context():
# #    db.create_all()
#     # Appears that Flask-SQLAlchemy doesn't support creation of Declarative classes.
#     # https://github.com/pallets-eco/flask-sqlalchemy/issues/1140
#     Base.metadata.create_all(db.engine)

#     db.session.add(Student(name="Jim Turner", grade=6, teacher="Ruiz", accessID="sjdhfd"))

#     s1 = Session(startDate=datetime.date(2023,9,5), endDate=datetime.date(2023,11,5), active=True)
#     db.session.add(s1)
#     db.session.add(Session(startDate=datetime.date(2023,11,6), endDate=datetime.date(2024,2,5), active=False))

#     db.session.add(Elective(session=s1, name="Bob's funhouse", lead="Bob Bobberson", maxAttendees=10, day="Monday", rotation=3, multisession=False, room="P3", consideredPE=False))
#     db.session.add(Elective(session=s1, name="Shoes", lead="Nancy Decker", maxAttendees=10, day="Wednesday", rotation=1, multisession=False, room="P3", consideredPE=True))
 
#     db.session.commit()
    s = db.select(Elective)
    r = db.session.execute(s)
#    all = r.all()

    for x in r.scalars():
        print(x)
        print(x.name)
        print(x.session.startDate)
    pdb.set_trace()
    print('woo')