import os
from flask import Flask, request, flash, redirect, send_file
from flask import render_template, Response, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func

import logging
import pprint
import json
import datetime
import csv
from itertools import zip_longest
import io
import zipfile

from database.configure import *

### 
### What's left
# x Elective Descriptions
# x Admin functionality to get things started
# x Output of schedules
# x Knowing which kids have yet to fill something out.
# x Cleaning up electives list
# x Modify student option in admin page
# x Need a schedule of which electives are held when (for pre-planning; just like college)
# testing
# Need a /x/demo account
# Fix the 0 seats bug
# "priority boarding" list

# Notes
# In session 2, we can use the AssignedClasses infrastructure to pull "part 2" electives out and auto-assign them.
# We need a better way to instantiate the database. It's only created at app launch time, which means racing deployment
#   or restarting the server if we fail. 

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
        app.logger.error(f"no matching student found for accessID {accessID}")
        return "<p>invalid access ID</p>", 401
    
    # Need...
    # The current session
    currentSession = RegistrationTools.activeSession()

    # See if this student is allowed to connect. `teacher` is the column name in the DB we key from
    teacherColumn = getattr(Session, student.teacher)
    subq = select(teacherColumn).select_from(Session).where(Session.active == True)
    isAllowToRegister = db.session.scalar(subq)
    if not isAllowToRegister:
        return render_template("notyet.html", teacher=student.teacher)

    # A list of electives for the current session
    subq = select(SessionElective).where(SessionElective.session == currentSession)
    electives = db.session.scalars(subq).fetchall()

    isEnrolledForSession = RegistrationTools.studentEnrolledForSession(student, currentSession)
    if isEnrolledForSession:
        app.logger.info(f"[{accessID}] already registered, showing schedule")
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
        R3_electiveIDs = list(map(lambda e: e.id, R3_electives))

        studentElectivesIDs = []
        app.logger.debug(f"[{accessID}] request.form: {request.form}")

        # If the form errors on a class being full and the student doesn't change it, it will be resubmitted as empty and not be part
        # of the request.form contents. We are always expecting 8, so anything less is a problem.
        if len(request.form.keys) < 8:
            # Find which ones are missing
            missing = []
            for day in ["monday", "wednesday", "thursday", "friday"]:
                for rotation in [1, 2]:
                    key = f"{day}_rotation_{rotation}"
                    if key not in request.form.keys:
                        missing.append(key)
            desc = ""
            for miss in missing:
                (day,rotation) = miss.split("_rotation_")
                if len(desc):
                    desc += ", "
                desc += f"{day.title()} R{rotation}"

            msg = f"You attempted to reselect a full elective on {desc}. This isn't valid and those entries have been reset. Please choose again."
            errors.append(msg)
            app.logger.error(f"[{accessID}] {msg}")
        else:
            for key in request.form:
                esID = int(request.form[key]) # everyone here expects this to be a number, including currentEnrollment
                studentElectivesIDs.append(esID)

                if esID in PE_electiveIDs:
                    PE_count += 1

                if esID in R3_electiveIDs:
                    partnerKey = key.replace("1","2") # Assume our id ends in 1
                    if key[-1] == "2":
                        partnerKey = key.replace("2", "1")
                    if request.form[key] != request.form[partnerKey]:
                        brokenRotation = list(filter(lambda e: e.id == esID, electives))[0]
                        msg = f"A double-rotation class '{brokenRotation.elective.name}' was not submitted as both rotation 1 and rotation 2. Make sure that <strong>{brokenRotation.day}</strong> has both rotations set to this elective."
                        errors.append(msg)
                        app.logger.error(f"[{accessID}] {msg}")

                # Did a class fill up between the form being loaded and submitted?
                if currentEnrollment[esID]["remaining"] == 0:
                    fullElective = list(filter(lambda e: e.id == esID, electives))[0]
                    msg = f"The class '{fullElective.elective.name}' on {fullElective.day} is now full. Please choose another elective."
                    errors.append(msg)
                    app.logger.error(f"[{accessID}] {msg}")

            if PE_count < 3:
                msg = f"You need at least 3 PE electives, you currently have {PE_count}. Look for electives with 🏈."
                errors.append(msg)
                app.logger.error(f"[{accessID}] {msg}")

            if len(studentElectivesIDs) != 8:
                msg = f"Critical application error! Unexpected count of elective IDs {studentElectivesIDs}. (this is not an error you can fix)"
                errors.append(msg)
                app.logger.error(f"[{accessID}] {msg}")
                app.logger.error(f"[{accessID}] studentElectivesIDs: {studentElectivesIDs}")

#        errors.append("This is a test error")
        if len(errors) > 0:
            previousForm = request.form
        else:
            # There are no errors! We can submit their schedule and show them the good news.
            studentElectives = list(filter(lambda e: e.id in studentElectivesIDs, electives))
            if len(studentElectives) != 8:
                msg = f"Critical application error! Unexpected count of student electives {studentElectives}. (this is not an error you can fix)"
                errors.append(msg)
                app.logger.error(f"[{accessID}] {msg}")
                app.logger.error(f"[{accessID}] studentElectivesIDs: {studentElectivesIDs}")
                foundNames = list(map(lambda se: f"se.id: {se.id} name: {se.elective.name}", studentElectives))
                app.logger.error(f"[{accessID}] studentElectives found: {foundNames}")
                previousForm = request.form
            else:
                (code, result) = RegistrationTools.registerStudent(student, studentElectives)

                if (code == "ok"):
                    return showSchedule(student, currentSession, studentElectives)
                else:
                    # Something has gone pretty wrong at this point. Database has failed to accept the addition.
                    err = f"[{accessID}] Failed to save results: {result}"
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

    electiveDescriptions = ""
    with open("electives/classes.json", 'r', encoding='utf-8') as f:
        electiveDescriptions = json.load(f)
    electiveDescriptions = sorted(electiveDescriptions, key=lambda d: d['v'])

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
                                                fri_r3_electives=fri_r3,
                                                electiveDescriptions=electiveDescriptions
                                                )

@app.route("/_admin_", methods=['GET', 'POST'])
def adminPage():
    if request.method == "POST":
        # if request.form["formID"] == "startSession":
        #     sessionNumber = request.form["sessionNumber"]
        #     sessionStartDate = request.form["sessionStartDate"] + " 07:00:00"

        #     date_format = '%Y-%m-%d %H:%M:%S'
        #     startDate = datetime.datetime.strptime(sessionStartDate, date_format)

        if request.form["formID"] == "modify_elective_assignment":
            studentID = int(request.form["modify_assignment_student"])
            student = db.session.execute(select(Student).where(Student.id == studentID)).scalar_one_or_none()
            if not student:
                flash("Could not find student record", 'error')
                return redirect(request.url)

            if request.form["addToElective"] != "no_change":
                se = db.session.execute(select(SessionElective).where(SessionElective.id == int(request.form["addToElective"]))).scalar_one_or_none()
                if not se:
                    flash("Failed to find session elective record for 'add to'", "error")
                    return redirect(request.url)

                s = Schedule(sessionElective=se)
                student.schedule.extend([s])

            if request.form["removeFromElective"] != "no_change":
                stmt = delete(Schedule).where(Schedule.studentID == student.id).where(Schedule.sessionElectiveID == int(request.form["removeFromElective"]))
                db.session.execute(stmt)

            db.session.commit()
            flash(f"Updated classes for {student.name}", "ok")
            return redirect(request.url)

        if request.form["formID"] == "elective_schedules":
            currentSession = RegistrationTools.activeSession()

            includeSeatCount = True if request.form["includeSeatsRemaining"] == "on" else False

            allR1 = [["Rotation 1"]]
            allR2 = [["Rotation 2"]]

            for day in ["Monday", "Wednesday", "Thursday", "Friday"]:
                r1 = []
                r2 = []
                subq = select(SessionElective).join(Elective).where(SessionElective.electiveID == Elective.id)\
                                                                                            .where(Elective.assignOnly == False)\
                                                                                            .where(SessionElective.day == day)\
                                                                                .join(Session).where(SessionElective.session == currentSession).order_by(Elective.name)
                sessionElectives = db.session.scalars(subq).fetchall()
                if includeSeatCount:
                    seatsLeft = RegistrationTools.currentEnrollmentCounts(sessionElectives)
                    for se in sessionElectives:
                        if se.rotation in [1,3]:
                            r1.append(f"{se.elective.name} ({seatsLeft[se.id]['remaining']} left)")
                        if se.rotation in [2,3]:
                            r2.append(f"{se.elective.name} ({seatsLeft[se.id]['remaining']} left)")
                else:
                    for se in sessionElectives:
                        if se.rotation in [1,3]:
                            r1.append(se.elective.name)
                        if se.rotation in [2,3]:
                            r2.append(se.elective.name)

                allR1.append(r1)
                allR2.append(r2)

            fileBuffer = io.StringIO()
            w = csv.writer(fileBuffer, quoting=csv.QUOTE_ALL)
            w.writerow(["", "Monday", "Wednesday", "Thursday", "Friday"])
            zl = zip_longest(*allR1)
            for z in zl:
                w.writerow(z)
            w.writerow(["","","","",""])
            zl = zip_longest(*allR2)
            for z in zl:
                w.writerow(z)

            return Response(fileBuffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition":f"attachment;filename=Session #{currentSession.number} Schedule of Electives.csv"})


        if request.form["formID"] == "enrollment_overview":
            currentSession = RegistrationTools.activeSession()

            # I feel this is something that the database should be able to do with enough subqueries but I couldn't quite get it figured out.
            # Maybe Future Jim™ will be smart enough to figure it out.
            studentNames = []
            allElectives = []
            subq = select(Student).order_by(Student.name)
            students = db.session.scalars(subq).fetchall()
            for day in ["Monday", "Wednesday", "Thursday", "Friday"]:
                r1 = []
                r2 = []
                for s in students:
                    if day == "Monday":
                        studentNames.append(s.name)

                    day_q = select(SessionElective).join(Elective).where(SessionElective.electiveID == Elective.id).where(SessionElective.day == day)\
                                            .join(Schedule).where(Schedule.sessionElectiveID == SessionElective.id).where(Schedule.studentID == s.id)\
                                            .join(Session).where(SessionElective.session == currentSession)

                    sessionElectives = db.session.scalars(day_q).fetchall()
                    r1_entry = ""
                    r2_entry = ""
                    for se in sessionElectives:
                        if se.rotation in [1,3]:
                            r1_entry = se.elective.name
                        if se.rotation in [2,3]:
                            r2_entry = se.elective.name
                    r1.append(r1_entry)
                    r2.append(r2_entry)

                allElectives.append(r1)
                allElectives.append(r2)
            
            allElectives.insert(0, studentNames)
            fileBuffer = io.StringIO()
            w = csv.writer(fileBuffer, quoting=csv.QUOTE_ALL)
            w.writerow(["", "Monday", "", "Wednesday", "", "Thursday", "", "Friday", ""])
            w.writerow(["","R1", "R2","R1", "R2","R1", "R2","R1", "R2"])
            zl = zip_longest(*allElectives)
            for z in zl:
                w.writerow(z)
            
            return Response(fileBuffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition":f"attachment;filename=Session #{currentSession.number} enrollment overview.csv"})

        if request.form["formID"] == "csv_schedules":
            currentSession = RegistrationTools.activeSession()
            zipBuffer = io.BytesIO()
            zipOutput = zipfile.ZipFile(zipBuffer, "w")

            for day in ["Monday", "Wednesday", "Thursday", "Friday"]:
                for rotation in [[1,3], [2,3]]:
                    electiveNames = []
                    electiveAttendees = []

                    subq = select(SessionElective).where(SessionElective.day == day).where(SessionElective.rotation.in_(rotation))\
                                                .join(Elective).where(SessionElective.electiveID == Elective.id)\
                                                .join(Session).where(SessionElective.session == currentSession).order_by(Elective.name)
                    sessionElectivesForDay = db.session.scalars(subq).fetchall()
                    for se in sessionElectivesForDay:
                        electiveNames.append(f"{se.elective.name}\r\n{se.elective.room}\r\n{se.elective.lead}")
                        subq = select(Student.name).select_from(Schedule).where(Schedule.sessionElectiveID == se.id).join(Student).where(Schedule.studentID == Student.id).order_by(Student.name)
                        students = db.session.scalars(subq).fetchall()
                        electiveAttendees.append(students)

                    f = io.StringIO()
                    w = csv.writer(f, quoting=csv.QUOTE_ALL)
                    w.writerow([day, f"Rotation {rotation[0]}", "1:05-1:50" if rotation[0] == 1 else "1:50-2:35"])
                    w.writerow(electiveNames)
                    zl = zip_longest(*electiveAttendees)
                    for z in zl:
                        w.writerow(z)

                    zipOutput.writestr(f"{day}_{rotation[0]}.csv", f.getvalue())

            zipOutput.close()
            return Response(zipBuffer.getvalue(), mimetype="application/zip", headers={"Content-Disposition":f"attachment;filename=Session #{currentSession.number} electives.zip"})
        
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
        students = db.session.scalars(select(Student).order_by(Student.name)).fetchall()
        return render_template('admin.html', studentCount=studentCount, students=students)

@app.route("/class/<classFile>", methods=['GET'])
def returnClassFile(classFile=None):
    if not classFile:
        return "<p>"

    if classFile == "_instruction.html":
        return "<p>"

# This is a nice to have at the moment... read all electives at once.
#    if classFile == "readall":

    return send_file("../electives/"+classFile)

# Only returns JSON
@app.route("/_json_/<task>")
def generateJSON(task=None):
    if not task:
        return jsonify()
    
    # Comes from the admin "modify assignments" page
    if task == "student_assignments":
        studentID = request.args.get("sID")
        targetSession = request.args.get("session")
        session = None
        if targetSession == "current":
            session = RegistrationTools.activeSession()
        else:
            session = db.session.execute(select(Session).where(Session.number == int(targetSession))).scalar_one_or_none()
        if not session:
            return jsonify({'error':'Could not locate session'})
        
        student = db.session.execute(select(Student).where(Student.id == studentID)).scalar_one_or_none()
        if not student:
            return jsonify({'error':'Unknown student ID'})
        
        dayOrder = ["Monday", "Wednesday", "Thursday", "Friday"]

        electives = RegistrationTools.chosenElectivesForSessions(student, session)
        enrollmentCounts = RegistrationTools.currentEnrollmentCounts(electives)
        sortedElectives = sorted(electives, key=lambda se: (dayOrder.index(se.day), se.rotation))
        seParts = []
        chosenElectiveIDs = []
        for se in sortedElectives:
            chosenElectiveIDs.append(se.id)
            seParts.append({'id':se.id, 'day':se.day, 'rotation':se.rotation, 'name':se.elective.name, 'seats_left':enrollmentCounts[se.id]["remaining"]})

        subq = select(SessionElective).where(SessionElective.id.not_in(chosenElectiveIDs))\
                                      .join(Session).where(SessionElective.session == session)
        remainingElectives = db.session.scalars(subq).fetchall()
        enrollmentCounts = RegistrationTools.currentEnrollmentCounts(remainingElectives)
        sortedRemainingElectives = sorted(remainingElectives, key=lambda se: (dayOrder.index(se.day), se.rotation))
        sreParts = []
        for sre in sortedRemainingElectives:
            sreParts.append({'id':sre.id, 'day':sre.day, 'rotation':sre.rotation, 'name':sre.elective.name, 'seats_left':enrollmentCounts[sre.id]["remaining"]})

        return jsonify({"enrolled":seParts, "available":sreParts})

    else:
        app.logger.error(f"json generator received unknown request: {task}")
        return jsonify()

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
#     currentSession = RegistrationTools.activeSession()

#     allR1 = [["Rotation 1"]]
#     allR2 = [["Rotation 2"]]

#     for day in ["Monday", "Wednesday", "Thursday", "Friday"]:
#         r1 = []
#         r2 = []
#         subq = select(SessionElective).join(Elective).where(SessionElective.electiveID == Elective.id)\
#                                                                                        .where(Elective.assignOnly == False)\
#                                                                                        .where(SessionElective.day == day)\
#                                                                         .join(Session).where(SessionElective.session == currentSession).order_by(Elective.name)
#         print(subq)
#         sessionElectives = db.session.scalars(subq).fetchall()
#         print(sessionElectives)
#         for se in sessionElectives:
#             if se.rotation in [1,3]:
#                 r1.append(se.elective.name)
#             if se.rotation in [2,3]:
#                 r2.append(se.elective.name)

#         allR1.append(r1)
#         allR2.append(r2)

#     csvPath = os.path.join("./instance", f"ElectiveSchedule.csv")
#     with open(csvPath, 'w', newline='') as f:
#         w = csv.writer(f, quoting=csv.QUOTE_ALL)
#         w.writerow(["", "Monday", "Wednesday", "Thursday", "Friday"])
#         zl = zip_longest(*allR1)
#         for z in zl:
#             w.writerow(z)

#         w.writerow(["","","","",""])
#         zl = zip_longest(*allR2)
#         for z in zl:
#             w.writerow(z)

#     pdb.set_trace()

#     electiveNames = []
#     electiveAttendees = []

    # currentSession = RegistrationTools.activeSession()
#     subq = select(SessionElective).where(SessionElective.day == "Monday").where(SessionElective.rotation.in_([1,3]))\
#                                 .join(Elective).where(SessionElective.electiveID == Elective.id)\
#                                 .join(Session).where(SessionElective.session == currentSession).order_by(Elective.name)
#     print(subq)
#     sessionElectivesForDay = db.session.scalars(subq).fetchall()
#     for se in sessionElectivesForDay:
#         electiveNames.append(f"{se.elective.name}\r\n{se.elective.room}\r\n{se.elective.lead}")
#         print(se.elective.name, se.id)
#         subq = select(Student.name).select_from(Schedule).where(Schedule.sessionElectiveID == se.id).join(Student).where(Schedule.studentID == Student.id).order_by(Student.name)
#         students = db.session.scalars(subq).fetchall()
#         electiveAttendees.append(students)

    # csvPath = os.path.join(abspath("."), "instance", f"Monday.csv")
    # with open(csvPath, 'w', newline='') as f:
        # w = csv.writer(f, quoting=csv.QUOTE_ALL)
        # w.writerow(["Monday", "Rotation 1", "1:05-1:50"])
    #     w.writerow(electiveNames)
    #     zl = zip_longest(*electiveAttendees)
    #     for z in zl:
    #         w.writerow(z)

#     pdb.set_trace()






    # currentSession = RegistrationTools.activeSession()
    # col_name = "active"
    # x = getattr(Session, col_name)
    # y = select(x).select_from(Session).where(Session.active == True)
    # print(x)
    # print(y)
    # z = db.session.scalar(y)
    # print(z)
    # pdb.set_trace()
#     electiveDescriptions = ""
#     with open("electives/classes.json", 'r', encoding='utf-8') as f:
#         electiveDescriptions = json.load(f)
#     electiveDescriptions = sorted(electiveDescriptions, key=lambda d: d['v'])
#     pprint.pprint(electiveDescriptions)
#     pdb.set_trace()

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
    # result = db.session.scalars(subq).fetchall()
    # print(result)
    # pdb.set_trace()
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