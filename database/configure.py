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

from sqlalchemy import select, func, and_, delete

import datetime
import pdb
import csv
import hashlib
import logging

logging.basicConfig(level=logging.DEBUG)

# Template folder location is relative to the file that creates the app (which is this file)
application = app = Flask(__name__, template_folder="../templates")
app.config["SECRET_KEY"] = "***REMOVED***"

# https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/using-features.managing.db.html?icmpid=docs_elasticbeanstalk_console
db_username = os.environ["RDS_USERNAME"]
db_password = os.environ["RDS_PASSWORD"]
db_host     = os.environ["RDS_HOSTNAME"]
db_port     = int(os.environ["RDS_PORT"])
db_name     = os.environ["RDS_DB_NAME"]

# A environmental key is set on the ElasticBeanstalk instance to let us know when this code is running local vs in AWS
if "INDIGO_AWS" in os.environ:
    app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql://{db_username}:{db_password}@{db_host}:{db_port}/{db_name}"
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///rsptest2.sqlite"

db = SQLAlchemy(app)

class Base(DeclarativeBase):
    pass

class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    accessID: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    grade: Mapped[int]
    teacher: Mapped[str] = mapped_column(String(128))
    schedule: Mapped[List["Schedule"]] = relationship(back_populates="student")

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int]
    startDate: Mapped[datetime.date]
    endDate: Mapped[datetime.date]
    active: Mapped[bool]
    Ruiz: Mapped[bool]
    Paolini: Mapped[bool]
    Bishop: Mapped[bool]
    electives: Mapped[List["SessionElective"]] = relationship(back_populates="session")

class Elective(Base):
    __tablename__ = "electives"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True)
    lead: Mapped[str] = mapped_column(String(128))
    maxAttendees: Mapped[int]
    multisession: Mapped[bool]
    room: Mapped[str] = mapped_column(String(128))
    consideredPE: Mapped[bool]
    assignOnly: Mapped[bool]

class SessionElective(Base):
    __tablename__ = "sessionelectives"
    id: Mapped[int] = mapped_column(primary_key=True)
    sessionID: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    electiveID: Mapped[int] = mapped_column(ForeignKey("electives.id"))
    day: Mapped[str] = mapped_column(String(32))
    rotation: Mapped[int]
    session: Mapped["Session"] = relationship(back_populates="electives")
    elective: Mapped["Elective"] = relationship(Elective, lazy="joined")

class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    # ForeignKeys are how the database makes connections. MappedColumns are how the ORM manages relationships. Both are needed if the magic is going to happen.
    studentID: Mapped[int] = mapped_column(ForeignKey("students.id"))
    student: Mapped["Student"] = relationship(back_populates="schedule")
    sessionElectiveID: Mapped[int] = mapped_column(ForeignKey("sessionelectives.id"))
    sessionElective: Mapped["SessionElective"] = relationship(SessionElective, lazy="joined")

class AssignedClasses(Base):
    __tablename__ = "assignedclasses"
    id: Mapped[int] = mapped_column(primary_key=True)
    studentID: Mapped[int]
    sessionElectiveID: Mapped[int]

with app.app_context():
# # #    db.create_all()
# #     # Appears that Flask-SQLAlchemy doesn't support creation of Declarative classes.
# #     # https://github.com/pallets-eco/flask-sqlalchemy/issues/1140
    # q = select(Session).where(Session.active == True)
    # currentSession = db.session.execute(q).scalar_one_or_none()

    # sel = select(SessionElective).where(SessionElective.session == currentSession)
    # r = db.session.scalars(sel)
    # electives = r.fetchall()
    # print(f"found {len(electives)}")
    # for se in electives:
    #     e = se.elective
    #     print(f"day: {se.day} rotation: {se.rotation} name: {e.name}")

    # mon_r1 = filter(lambda e: e.day == "Monday" and e.rotation == 1, electives)
    # for se in mon_r1:
    #     e = se.elective
    #     print(f"day: {se.day} rotation: {se.rotation} name: {e.name}")

    doDBStuff = True
    insertTestData = False
    if doDBStuff:
        Base.metadata.create_all(db.engine)

        if insertTestData:
            db.session.add(Student(name="Jake Turner", grade=6, teacher="Ruiz", accessID="sjdhfd"))
            db.session.add(Student(name="Mike Smith", grade=7, teacher="Vong", accessID="xxx888"))
            jim = Student(name="Jim Turner", grade=6, teacher="Ruiz", accessID="999771")
            db.session.add(jim)

            s1 = Session(startDate=datetime.date(2023,9,5), endDate=datetime.date(2023,11,5), active=True)
            db.session.add(s1)
            s2 = Session(startDate=datetime.date(2023,11,6), endDate=datetime.date(2024,2,5), active=False)
            db.session.add(s2)

            e1 = Elective(name="Bob's funhouse", lead="Bob Bobberson", maxAttendees=10, multisession=False, room="P3", consideredPE=False)
            db.session.add(e1)
            e2 = Elective(name="Cooking", lead="Joni Cimoli", maxAttendees=8, multisession=False, room="Kitchen", consideredPE=False)
            db.session.add(e2)
            e3 = Elective(name="Shoes", lead="Nancy Decker", maxAttendees=10, multisession=False, room="P3", consideredPE=True)
            db.session.add(e3)
            db.session.commit()

            se11 = SessionElective(day="Monday", rotation=1, session=s1, elective=e1)
            se12 = SessionElective(day="Monday", rotation=2, session=s1, elective=e1)
            se21 = SessionElective(day="Monday", rotation=1, session=s1, elective=e2)
            se22 = SessionElective(day="Thursday", rotation=1, session=s1, elective=e2)
            se31 = SessionElective(day="Wednesday", rotation=1, session=s1, elective=e3)
            se32 = SessionElective(day="Wednesday", rotation=2, session=s1, elective=e3)
            db.session.add_all([se11, se12, se21, se22, se31, se32])
            db.session.commit()

            jim.schedule.append(Schedule(sessionElective=se12))
            jim.schedule.append(Schedule(sessionElective=se22))
            jim.schedule.append(Schedule(sessionElective=se32))
            db.session.commit()

            r = db.session.scalars(select(Schedule).where(Schedule.studentID == 3)).all()
            print(f"Found {len(r)} entries for {r[0].student.name}")
            for schedule in r:
                se = schedule.sessionElective
                e = se.elective
                print(f"{e.name} on {se.day} lead by {e.lead}")

####################################################################################

class RegistrationTools():
    # Returns the current enrollment of all SessionElectives. 
    # Requires you pass in a list of SessionElectives
    # TODO - jimt - There has got to be a way to return this count with the list of SessionElectives, but hell if I know how to do it in SQLAlchemy.
    @classmethod
    def currentEnrollmentCounts(cls, sessionElectives):
        subq = select(Schedule.sessionElectiveID, func.count("*").label("count")).select_from(Schedule).group_by(Schedule.sessionElectiveID)
        result = dict(db.session.execute(subq).fetchall())

        counts = {}
        for se in sessionElectives:
            enrolled = 0
            if se.id in result:
                enrolled = result[se.id]

            counts[se.id] = { 'enrolled': enrolled, 'remaining': se.elective.maxAttendees - enrolled }

        return counts
    
    @classmethod
    def activeSession(cls):
        q = select(Session).where(Session.active == True)
        result = db.session.execute(q).scalar_one_or_none()
        return result


    @classmethod
    def registerStudent(cls, student, electives):
        schedule = []
        for se in electives:
            s = Schedule(sessionElective=se)
            schedule.append(s)

        #TODO - jimt - If this ever gets re-run, it'll extend instead of replace. Probably should replace.
        student.schedule.extend(schedule)
        db.session.commit()

        # Assuming it all went well, drop from AssignedClasses any entries, if any. 
        stmt = delete(AssignedClasses).where(AssignedClasses.studentID == student.id)
        db.session.execute(stmt)
        db.session.commit()

        return('ok', "Registered!")
    
    @classmethod
    def studentEnrolledForSession(cls, student, session=None):
        if not session:
            session = RegistrationTools.activeSession()
        
        subq = select(func.count(Schedule.studentID)).select_from(Schedule).join(SessionElective).where(Schedule.studentID == student.id)\
                                                                           .join(Session).where(SessionElective.session == session)
        count = db.session.scalar(subq)
        return (count > 4) # rotation=3 electives make this not likely to be 8 exactly. So anyone who's got more than four saved is registered 
                           # (assuming they picked four rotation=3 electives)

    # Returns a list of SessionElective objects
    @classmethod
    def chosenElectivesForSessions(cls, student, session=None):
        if not session:
            session = RegistrationTools.activeSession()

        subq = select(SessionElective).select_from(Schedule).join(SessionElective).where(Schedule.studentID == student.id)\
                                                            .join(Session).where(SessionElective.session == session)
        result = db.session.scalars(subq).fetchall()
        return result

    @classmethod
    def findScheduledClasses(cls, student):
        subq = select(AssignedClasses).where(AssignedClasses.studentID == student.id)
        result = db.session.scalars(subq).fetchall()
        if len(result) > 0:
            seIDs = list(map(lambda e: e.sessionElectiveID ,result))
            subq = select(SessionElective).where(SessionElective.id.in_(seIDs))
            result = db.session.scalars(subq).fetchall()
            return result
        else:
            return None

class ConfigUtils():
    @classmethod
    def uploadSessions(cls, data=None):
        if not data:
            return('error', "No data found")
        
        r = csv.DictReader(data)
        date_format = '%Y-%m-%d'
        for row in r:
            startDate = datetime.datetime.strptime(row["startDate"], date_format)
            endDate = datetime.datetime.strptime(row["endDate"], date_format)
            db.session.add(Session(number=int(row["sessionNumber"]), startDate=startDate, endDate=endDate, active=(row["active"]=="TRUE"),
                                   Ruiz=(row["Ruiz"]=="TRUE"),Paolini=(row["Paolini"]=="TRUE"),Bishop=(row["Bishop"]=="TRUE")))

        db.session.commit()
            
        return('ok', 'Sessions uploaded')


    @classmethod
    def uploadRoster(cls, data=None):
        if not data:
            return('error', "No data found")

        r = csv.DictReader(data)
        for row in r:
#            app.logger.info(row["name"])
            key = row["name"] + "|" + row["class"] + "|" + row["grade"]
            md5hash = hashlib.md5(key.encode()).hexdigest()
            first7 = md5hash[:7]
            db.session.add(Student(name=row["name"], grade=row["grade"][:1], teacher=row["class"], accessID=first7))

        db.session.commit()
            
        return('ok', 'Roster uploaded')

    @classmethod
    def uploadElectives(cls, data=None, sessionNumber=None):
        if not data:
            return('error', "No data found")
        if not sessionNumber:
            return('error', "Session number is required")
        
        session = db.session.scalars(select(Session).where(Session.id == sessionNumber)).first()

        r = csv.DictReader(data)
        for row in r:
            # app.logger.info(f"{sessionNumber}: {row['name']} - {row['rotations']}")
            # Create an entry into the electives table. It may already exist, so we should consider updating it. 
            elective = Elective(name=row['name'], lead=row['lead'], maxAttendees=int(row['maxAttendees']), multisession=(row["multisession"]=="TRUE"), 
                                room=row["room"], consideredPE=(row["consideredPE"]=="TRUE"), assignOnly=(row["assignOnly"]=="TRUE"))
            db.session.add(elective)
            try:
                db.session.commit()
            except IntegrityError as error:
                # TODO - jimt - Allow updating entries in the database, not just ignoring.
                if "UNIQUE constraint failed: electives.name" not in str(error):
                    app.logger.error(error)
                    return('error', "DB error")
                
                db.session.rollback()
                # There's already an elective in the database. Get a reference to that one instead.
                elective = db.session.scalars(select(Elective).where(Elective.name == row['name'])).first()

            for rotation in row["rotations"].split(","):
                if row["day"] == "*":
                    # Every day gets this elective/rotation (it's most likely PE or RSP)
                    for day in ["Monday", "Wednesday", "Thursday", "Friday"]:
                        se = SessionElective(day=day, rotation=rotation, session=session, elective=elective)
                        db.session.add(se)
                else:
                    se = SessionElective(day=row["day"], rotation=rotation, session=session, elective=elective)
                    db.session.add(se)

            db.session.commit()

        return('ok', f"Electives uploaded for session {sessionNumber}")
    
    @classmethod
    def uploadSpecificAssignments(cls, data=None, sessionNumber=None):
        if not data:
            return('error', "No data found")
        if not sessionNumber:
            return('error', "Session number is required")
        
        session = db.session.scalars(select(Session).where(Session.number == sessionNumber)).first()
        countOfAssignments = 0
        r = csv.DictReader(data)
        for row in r:
            # Find the student and the elective they need to take.
            sel = select(Student).where(Student.name == row["student"])
            r = db.session.execute(sel)
            student = r.scalar_one_or_none()
            if not student:
                db.session.rollback()
                return('error', f"Could not find a student record for {row['student']}")

            scheduledElectives = []
            for day in ["Monday", "Wednesday", "Thursday", "Friday"]:
                electiveName = row[day]
                if electiveName:
                    subq = select(SessionElective).select_from(Elective).where(Elective.name.startswith(electiveName)).join(SessionElective)\
                                                                        .where(SessionElective.electiveID == Elective.id)\
                                                                        .where(SessionElective.rotation == int(row["rotation"]))\
                                                                        .where(SessionElective.day == day)\
                                                                        .join(Session).where(SessionElective.session == session)

                    se = db.session.execute(subq).scalar_one_or_none()
                    if not se:
                        db.session.rollback()
                        return('error', f"Could not find a matching elective name starting with {electiveName} on {day} rotation {row['rotation']}")
                    assignment = AssignedClasses(studentID=student.id, sessionElectiveID=se.id)
                    db.session.add(assignment)
                    countOfAssignments += 1

        db.session.commit()
        return('ok', f"Performed {countOfAssignments} assignments.")
        
    # @classmethod
    # def old_uploadSpecificAssignments(cls, data=None, sessionNumber=None):
    #     if not data:
    #         return('error', "No data found")
    #     if not sessionNumber:
    #         return('error', "Session number is required")
        
    #     session = db.session.scalars(select(Session).where(Session.number == sessionNumber)).first()

    #     countOfAssignments = 0
    #     r = csv.DictReader(data)
    #     for row in r:
    #         # Find the student and the elective they need to take.
    #         sel = select(Student).where(Student.name == row["student"])
    #         r = db.session.execute(sel)
    #         student = r.scalar_one_or_none()
    #         if not student:
    #             db.session.rollback()
    #             return('error', f"Could not find a student record for {row['student']}")

    #         scheduledElectives = []
    #         for day in ["Monday", "Wednesday", "Thursday", "Friday"]:
    #             electiveName = row[day]
    #             if electiveName:
    #                 subq = select(SessionElective).select_from(Elective).where(Elective.name.startswith(electiveName)).join(SessionElective)\
    #                                                                     .where(SessionElective.electiveID == Elective.id)\
    #                                                                     .where(SessionElective.rotation == int(row["rotation"]))\
    #                                                                     .where(SessionElective.day == day)\
    #                                                                     .join(Session).where(SessionElective.session == session)

    #                 se = db.session.execute(subq).scalar_one_or_none()
    #                 if not se:
    #                     db.session.rollback()
    #                     return('error', f"Could not find a matching elective name starting with {electiveName} on {day} rotation {row['rotation']}")
    
    #                 s = Schedule(sessionElective=se)
    #                 scheduledElectives.append(s)
    #                 countOfAssignments += 1
            
    #         student.schedule.extend(scheduledElectives)

    #     db.session.commit()
    #     return('ok', f"Performed {countOfAssignments} assignments.")