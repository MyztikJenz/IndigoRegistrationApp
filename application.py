import os
from flask import Flask, request, flash, redirect, send_file
from flask import render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func

import logging
import pprint

from database.configure import *

@app.route("/")
def hello_world():
    str = "<p>Hello, World!</p>"
    return str

@app.route("/x")
@app.route("/x/<accessID>")
def registrationPage(accessID=None):
    if not accessID:
        return "<p>" # show nothing if someone just happens to find this page and doesn't provide an accessID

    sel = select(Student).where(Student.accessID == accessID)
    r = db.session.execute(sel)
    student = r.scalar_one_or_none()
    if not student:
        return "<p>invalid access ID</p>", 401
    
    # Need...
    currentSession = RegistrationTools.activeSession()
    # A list of electives for the current session
 #   sessionNumber = 1

    sel = select(SessionElective).where(SessionElective.session == currentSession)
    r = db.session.scalars(sel)
    electives = r.fetchall()

    # the count of seats already occupied
    currentEnrollment = RegistrationTools.currentEnrollmentCounts(electives)

    # for se in electives:
    #     if se.id in currentEnrollment:
    #         app.logger.info(f"Found elective with enrollment")





    # TODO - jimt - Would be nice if the classes were ordered alphabetically

    mon_r1 = list(filter(lambda e: e.day == "Monday" and e.rotation == 1, electives))
    mon_r2 = list(filter(lambda e: e.day == "Monday" and e.rotation == 2, electives))
    wed_r1 = list(filter(lambda e: e.day == "Wednesday" and e.rotation == 1, electives))
    wed_r2 = list(filter(lambda e: e.day == "Wednesday" and e.rotation == 2, electives))
    thu_r1 = list(filter(lambda e: e.day == "Thursday" and e.rotation == 1, electives))
    thu_r2 = list(filter(lambda e: e.day == "Thursday" and e.rotation == 2, electives))
    fri_r1 = list(filter(lambda e: e.day == "Friday" and e.rotation == 1, electives))
    fri_r2 = list(filter(lambda e: e.day == "Friday" and e.rotation == 2, electives))

    mon_r3 = list(filter(lambda e: e.day == "Monday" and e.rotation == 3, electives))
    wed_r3 = list(filter(lambda e: e.day == "Wednesday" and e.rotation == 3, electives))
    thu_r3 = list(filter(lambda e: e.day == "Thursday" and e.rotation == 3, electives))
    fri_r3 = list(filter(lambda e: e.day == "Friday" and e.rotation == 3, electives))

    # Any electives that contain "exclusions", students that should not be placed together and are alread in a class
    #

    return render_template('registration.html', student=student, currentEnrollment=currentEnrollment,
                                                mon_r1_electives=mon_r1, mon_r2_electives=mon_r2,
                                                wed_r1_electives=wed_r1, wed_r2_electives=wed_r2,
                                                thu_r1_electives=thu_r1, thu_r2_electives=thu_r2,
                                                fri_r1_electives=fri_r1, fri_r2_electives=fri_r2,
                                                mon_r3_electives=mon_r3,
                                                wed_r3_electives=wed_r3,
                                                thu_r3_electives=thu_r3,
                                                fri_r3_electives=fri_r3
                                                )

@app.route("/_admin_", methods=['GET', 'POST'])
def adminPage():
    if request.method == "POST":
        if request.form["formID"] == "session_upload":
            if 'sessions' not in request.files:
                flash("No session found", 'error')
                return redirect(request.url)

            sessions = request.files['sessions']
            if sessions.filename == '':
                flash("No selected file", 'error')
                return redirect(request.url)
            
            sessions = map(lambda x: str(x, 'utf-8'), sessions)
            (code, result) = ConfigUtils.uploadSessions(sessions)
            flash(result, code)
            return redirect(request.url)


        if request.form["formID"] == "roster_upload":
            if 'roster' not in request.files:
                flash("No roster found", 'error')
                return redirect(request.url)

            roster = request.files['roster']
            if roster.filename == '':
                flash("No selected file", 'error')
                return redirect(request.url)
            
            if roster:
                # roster should be a FileStorage object, which is a basic file wrapper. But it's 
                # encoded as a binary string. Convert it to a list of utf-8 strings.
                roster = map(lambda x: str(x, 'utf-8'), roster)
                (code, result) = ConfigUtils.uploadRoster(roster)
                flash(result, code)
                return redirect(request.url)
            
        elif request.form["formID"] == "elective_upload":
            if 'electives' not in request.files:
                flash("No electives found", 'error')
                return redirect(request.url)
            
            electives = request.files['electives']
            if electives.filename == '':
                flash("No selected file", 'error')
                return redirect(request.url)
            
            electives = map(lambda x: str(x, 'utf-8'), electives)
            sessionNumber = request.form["sessionNumber"]
            (code, result) = ConfigUtils.uploadElectives(electives, sessionNumber)
            flash(result, code)
            return redirect(request.url)
        else:
            flash("Unknown formID", 'error')
            return redirect(request.url)
    else:
        studentCount = db.session.query(func.count(Student.id)).scalar()
        return render_template('admin.html', studentCount=studentCount)

@app.route("/class/<classFile>", methods=['GET'])
def returnClassFile(classFile=None):
    if not classFile:
        return "<p>"

    if classFile == "_instruction.html":
        return "<p>"

# This is a nice to have at the moment... read all electives at once.
#    if classFile == "readall":

    return send_file("../electives/"+classFile)

# @app.route("/t")
# @app.route("/t/<varName>")
# def show_template(varName=None):
#     dbError = None
#     if varName:
#         try:
#             db.session.add(User(name=varName))
#             db.session.commit()
#         except IntegrityError as err:
#             print(f"Crap... {err}")
#             dbError = err
#             db.session.rollback()

#     rowCount = db.session.query(User).count()

#     return render_template('test.html', varName=varName, nameCount=rowCount, dbError=dbError)

#with app.app_context():
#     currentSession = RegistrationTools.activeSession()
#     # A list of electives for the current session
#  #   sessionNumber = 1

#     sel = select(SessionElective).where(SessionElective.session == currentSession)
#     r = db.session.scalars(sel)
#     electives = r.fetchall()

#     # the count of seats already occupied
#     currentEnrollment = RegistrationTools.currentEnrollmentCounts(electives)
#     pprint.pprint(currentEnrollment)
#    db.create_all()

    # db.session.add(User(name="test2"))
    # db.session.commit()

    # users = db.session.execute(db.select(User)).scalars()

    # s = db.select(Elective)
    # r = db.session.execute(s)
    # all = r.all()
    # print(all)