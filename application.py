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
@app.route("/x/<accessID>", methods=['GET', 'POST'])
def registrationPage(accessID=None):
    if not accessID:
        return "<p>" # show nothing if someone just happens to find this page and doesn't provide an accessID

    sel = select(Student).where(Student.accessID == accessID)
    r = db.session.execute(sel)
    student = r.scalar_one_or_none()
    if not student:
        return "<p>invalid access ID</p>", 401
    
    # Need...
    # The current session
    currentSession = RegistrationTools.activeSession()

    # A list of electives for the current session
    sel = select(SessionElective).where(SessionElective.session == currentSession)
    r = db.session.scalars(sel)
    electives = r.fetchall()

    isEnrolledForSession = RegistrationTools.studentEnrolledForSession(student, currentSession)
    if isEnrolledForSession:
        return showSchedule(student, currentSession)

    # the count of seats already occupied
    currentEnrollment = RegistrationTools.currentEnrollmentCounts(electives)

    previousForm = {}
    errors = []
    if request.method == "POST":
        # Did they select enough PE?
        PE_electives = list(filter(lambda e: e.elective.consideredPE, electives))
        PE_electiveIDs = list(map(lambda e: e.id, PE_electives))
        PE_count = 0

        # Did rotation=3 electives stay together (rotation1 and rotation2 need to match)
        R3_electives = list(filter(lambda e: e.rotation == 3, electives))
        RE_electiveIDs = list(map(lambda e: e.id, R3_electives))

        studentElectivesIDs = []
        for key in request.form:
            esID = int(request.form[key]) # everyone here expects this to be a number, including currentEnrollment
            studentElectivesIDs.append(esID)

            if esID in PE_electiveIDs:
                PE_count += 1

            if esID in RE_electiveIDs:
                partnerKey = key.replace("1","2") # Assume our id ends in 1
                if key[-1] == "2":
                    partnerKey = key.replace("2", "1")
                if request.form[key] != request.form[partnerKey]:
                    brokenRotation = list(filter(lambda e: e.id == esID, electives))[0]
                    errors.append(f"A double-rotation class '{brokenRotation.elective.name}' was not submitted as both rotation 1 and rotation 2. Make sure that <strong>{brokenRotation.day}</strong> has both rotations set to this elective.")

            # Did a class fill up between the form being loaded and submitted?
            if currentEnrollment[esID]["remaining"] == 0:
                fullElective = list(filter(lambda e: e.id == esID, electives))[0]
                errors.append(f"The class '{fullElective.elective.name}' is now full. Please choose another.")

        if PE_count < 3:
            errors.append(f"You need at least 3 PE electives, you currently have {PE_count}. Look for electives with 🏈.")

#        errors.append("This is a test error")
        if len(errors) > 0:
            previousForm = request.form
        else:
            # There are no errors! We can submit their schedule and show them the good news.
            studentElectives = list(filter(lambda e: e.id in studentElectivesIDs, electives))
            (code, result) = RegistrationTools.registerStudent(student, studentElectives)

            if (code == "ok"):
                return showSchedule(student, currentSession, studentElectives)
            else:
                # Something has gone pretty wrong at this point. Database has failed to accept the addition.
                err = f"Failed to save results: {result}"
                app.logger.error(err)
                return err

    # END if request.method == "POST":

    # Does the student already have classes enrolled? If so, those are mandatory and need to replace any options they may have.
    # This is terribly gross. I'm sure there's a more elegant way of doing this, but I don't see it at the moment.
    all_mandatory_electives = RegistrationTools.findScheduledClasses(student)
    if not all_mandatory_electives:
        all_mandatory_electives = [] # if there's no scheduled classes, make the filter happy

    # TODO - jimt - Would be nice if the classes were ordered alphabetically

    mon_r1_mandatory = list(filter(lambda e: e.day == "Monday" and e.rotation == 1, all_mandatory_electives))
    if len(mon_r1_mandatory) > 0:
        mon_r1 = mon_r1_mandatory
    else:
        mon_r1 = list(filter(lambda e: e.day == "Monday" and e.rotation == 1 and e.elective.assignOnly == False, electives))

    mon_r2_mandatory = list(filter(lambda e: e.day == "Monday" and e.rotation == 2, all_mandatory_electives))
    if len(mon_r2_mandatory) > 0:
        mon_r2 = mon_r2_mandatory
    else:
        mon_r2 = list(filter(lambda e: e.day == "Monday" and e.rotation == 2 and e.elective.assignOnly == False, electives))

    wed_r1_mandatory = list(filter(lambda e: e.day == "Wednesday" and e.rotation == 1, all_mandatory_electives))
    if len(wed_r1_mandatory) > 0:
        wed_r1 = wed_r1_mandatory
    else:
        wed_r1 = list(filter(lambda e: e.day == "Wednesday" and e.rotation == 1 and e.elective.assignOnly == False, electives))

    wed_r2_mandatory = list(filter(lambda e: e.day == "Wednesday" and e.rotation == 2, all_mandatory_electives))
    if len(wed_r2_mandatory) > 0:
        wed_r2 = wed_r2_mandatory
    else:
        wed_r2 = list(filter(lambda e: e.day == "Wednesday" and e.rotation == 2 and e.elective.assignOnly == False, electives))

    thu_r1_mandatory = list(filter(lambda e: e.day == "Thursday" and e.rotation == 1, all_mandatory_electives))
    if len(thu_r1_mandatory) > 0:
        thu_r1 = thu_r1_mandatory
    else:
        thu_r1 = list(filter(lambda e: e.day == "Thursday" and e.rotation == 1 and e.elective.assignOnly == False, electives))
  
    thu_r2_mandatory = list(filter(lambda e: e.day == "Thursday" and e.rotation == 2, all_mandatory_electives))
    if len(thu_r2_mandatory) > 0:
        thu_r2 = thu_r2_mandatory
    else:
        thu_r2 = list(filter(lambda e: e.day == "Thursday" and e.rotation == 2 and e.elective.assignOnly == False, electives))

    fri_r1_mandatory = list(filter(lambda e: e.day == "Friday" and e.rotation == 1, all_mandatory_electives))
    if len(fri_r1_mandatory) > 0:
        fri_r1 = fri_r1_mandatory
    else:
        fri_r1 = list(filter(lambda e: e.day == "Friday" and e.rotation == 1 and e.elective.assignOnly == False, electives))

    fri_r2_mandatory = list(filter(lambda e: e.day == "Friday" and e.rotation == 2, all_mandatory_electives))
    if len(fri_r2_mandatory) > 0:
        fri_r2 = fri_r2_mandatory
    else:
        fri_r2 = list(filter(lambda e: e.day == "Friday" and e.rotation == 2 and e.elective.assignOnly == False, electives))

    mon_r3 = wed_r3 = thu_r3 = fri_r3 = []
    if len(mon_r1_mandatory) == 0 and len(mon_r2_mandatory) == 0:
        mon_r3 = list(filter(lambda e: e.day == "Monday" and e.rotation == 3, electives))

    if len(wed_r1_mandatory) == 0 and len(wed_r2_mandatory) == 0:
        wed_r3 = list(filter(lambda e: e.day == "Wednesday" and e.rotation == 3, electives))
    
    if len(thu_r1_mandatory) == 0 and len(thu_r2_mandatory) == 0:
        thu_r3 = list(filter(lambda e: e.day == "Thursday" and e.rotation == 3, electives))

    if len(fri_r1_mandatory) == 0 and len(fri_r2_mandatory) == 0:
        fri_r3 = list(filter(lambda e: e.day == "Friday" and e.rotation == 3, electives))

    # TODO - jimt - Any electives that contain "exclusions", students that should not be placed together and are alread in a class

    return render_template('registration.html', student=student, currentEnrollment=currentEnrollment, session=currentSession,
                                                previousForm=previousForm, errors=errors,
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

        elif request.form["formID"] == "specific_assignment":
            if 'assignments' not in request.files:
                flash("No assignments found", 'error')
                return redirect(request.url)
            
            assignments = request.files['assignments']
            if assignments.filename == '':
                flash("No selected file", 'error')
                return redirect(request.url)
            
            assignments = map(lambda x: str(x, 'utf-8'), assignments)
            sessionNumber = request.form["sessionNumber"]
            (code, result) = ConfigUtils.uploadSpecificAssignments(assignments, sessionNumber)
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

# Not a flask route. Only called internally, but from inside flask contexts.
# This function needs to return to its caller what it wants to show on the screen.
def showSchedule(student, session=None, electives=None):
    if not session:
        session = RegistrationTools.activeSession
    
    if not electives:
        electives = RegistrationTools.chosenElectivesForSessions(student, session)

    mon_r1 = list(filter(lambda e: e.day == "Monday" and e.rotation in [1,3], electives))[0]
    wed_r1 = list(filter(lambda e: e.day == "Wednesday" and e.rotation in [1,3], electives))[0]
    thu_r1 = list(filter(lambda e: e.day == "Thursday" and e.rotation in [1,3], electives))[0]
    fri_r1 = list(filter(lambda e: e.day == "Friday" and e.rotation in [1,3], electives))[0]
    mon_r2 = list(filter(lambda e: e.day == "Monday" and e.rotation in [2,3], electives))[0]
    wed_r2 = list(filter(lambda e: e.day == "Wednesday" and e.rotation in [2,3], electives))[0]
    thu_r2 = list(filter(lambda e: e.day == "Thursday" and e.rotation in [2,3], electives))[0]
    fri_r2 = list(filter(lambda e: e.day == "Friday" and e.rotation in [2,3], electives))[0]

    return render_template('schedule.html', student=student, session=session,
                                            mon_r1=mon_r1, wed_r1=wed_r1, thu_r1=thu_r1, fri_r1=fri_r1, 
                                            mon_r2=mon_r2, wed_r2=wed_r2, thu_r2=thu_r2, fri_r2=fri_r2 
                                            )

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

# with app.app_context():
#     stmt = delete(AssignedClasses).where(AssignedClasses.studentID == 15)
#     db.session.execute(stmt)    
#     db.session.commit()

#     sel = select(Student).where(Student.accessID == 'bab3e0d')
#     r = db.session.execute(sel)
#     student = r.scalar_one_or_none()
#     result = RegistrationTools.findScheduledClasses(student)
#     print(result)
#     pdb.set_trace()
#     currentSession = RegistrationTools.activeSession()
#     subq = select(SessionElective).select_from(Schedule).where(Schedule.student == student).join(SessionElective)\
#                                                         .where(Schedule.sessionElectiveID == SessionElective.id)\
#                                                         .where(SessionElective.day == "Monday")\
#                                                         .where(SessionElective.rotation == 1)\
#                                                         .join(Session).where(SessionElective.session == currentSession)
#     print(subq)
#     result = db.session.scalars(subq).fetchall()
#     print(result)
#     pdb.set_trace()
#     print(result[0].elective.name)

#     currentSession = RegistrationTools.activeSession()
#     subq = select(SessionElective).select_from(Elective).where(Elective.name.startswith("Ba")).join(SessionElective)\
#                                                         .where(SessionElective.electiveID == Elective.id)\
#                                                         .where(SessionElective.rotation == 1)\
#                                                         .where(SessionElective.day == "Monday")\
#                                                         .join(Session).where(SessionElective.session == currentSession)
#     print(subq)
#     result = db.session.execute(subq).scalar_one_or_none()
#     print(result)
#     print(result.elective.name)
#     pdb.set_trace()
#     currentSession = RegistrationTools.activeSession()

#     sel = select(Student).where(Student.accessID == 'sjdhfd')
#     r = db.session.execute(sel)
#     student = r.scalar_one_or_none()


# #    subq = select(Schedule.sessionElectiveID, func.count("*").label("count")).select_from(Schedule).group_by(Schedule.sessionElectiveID).where(and_(Schedule.studentID == student.id, Schedule.sessionElective.sessionID == currentSession.id))
#     subq = select(SessionElective).select_from(Schedule).join(SessionElective).where(Schedule.studentID == student.id)\
#     .join(Session).where(SessionElective.session == currentSession)
#                                                                             #.where(Schedule.sessionElectiveID == currentSession.id)
#     print(subq)
#     result = db.session.scalars(subq).fetchall()
#     print(result)
#     for x in result:
#         print(x.elective.name)
#     pdb.set_trace()
#     # A list of electives for the current session
#  #   sessionNumber = 1

#     sel = select(SessionElective).where(SessionElective.session == currentSession)
#     r = db.session.scalars(sel)
#     electives = r.fetchall()

#     # the count of seats already occupied
#     currentEnrollment = RegistrationTools.currentEnrollmentCounts(electives)

#     x = 64
#     print(currentEnrollment[x]["remaining"])
#     pprint.pprint(currentEnrollment)
#    db.create_all()

    # db.session.add(User(name="test2"))
    # db.session.commit()

    # users = db.session.execute(db.select(User)).scalars()

    # s = db.select(Elective)
    # r = db.session.execute(s)
    # all = r.all()
    # print(all)