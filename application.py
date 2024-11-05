import os
from flask import Flask, request, flash, redirect, send_file
from flask import render_template, Response, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func, or_

import logging
import pprint
import json
import datetime
import csv
from itertools import zip_longest
import io
import zipfile
import uwsgidecorators
import uwsgi
import time

from database.configure import *

### 
### What's left
# testing
# Fix the 0 seats bug (in HTML, backend is fixed) [Not sure how realistic this is... it's a hard problem to solve]
#   This is how to avoid reloading the page on the a class with zero seats available when the form reloads. Feels like we can have "choose one" options that are the defaults
# Sanitize the accessID. Someone's putting extra non-printable characters at the end (or something...)
#   no matching student found for accessID 1c5e3f5 אדוויקספפרדספדס
#
# Very nice to have (it's a pain right now)
# Editing a student's schedule is a pain right now, needs to be better
#   And available to teachers (if they are so inclined)
#   Perhaps there's another page that loads the same thing students see, but with all options available. Would allow me to see everything all at once.
#       Needs to be separate, it's a back-door otherwise
# Is there a way to detect over-filled multisession classes and expand their max size to accommodate? May not be worth the effort.
#
# Required before next session
# Move service-related data into the environment
#   see https://help.pythonanywhere.com/pages/environment-variables-for-web-apps/
#
# DONE
# Reset from last year - clear out the database
# Enable option to allow studends to enroll by grade level
# Should we limit PE? To what? and how?
#   this was a significant problem in Session 4. It does need to be limited, gut feeling is to 5 given the makeup of the offerings we had in 2023-24
# When the form switches the other popup to support multi-rotation electives, there needs to be a callout that it happened. Too many are missing the change.
# Need a /x/demo account
# Schedule viewer (not just download)
# Option to prevent classes from being taken in back-to-back rotations (not sessions)
#   But not PE


@app.route("/")
def hello_world():
    str = "<p>Hello, World!</p>"
    return str

@app.route("/x")
@app.route("/x/<accessID>", methods=['GET', 'POST'])
def registrationPage(accessID=None):
    if not accessID:
        return "<p>" # show nothing if someone just happens to find this page and doesn't provide an accessID

    if accessID == "studentdemo":
        student = Student(name="Test Student", grade=6, teacher="Ruiz", accessID="studentdemo")
    else:
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
    isAllowToRegisterByTeacher = db.session.scalar(subq)

    gradeColumnName = "sixthGrade" if student.grade == 6 else "seventhGrade" if student.grade == 7 else "eigthGrade"
    gradeColumn = getattr(Session, gradeColumnName)
    subq = select(gradeColumn).select_from(Session).where(Session.active == True)
    isAllowToRegisterByGrade = db.session.scalar(subq)

    isAllowToRegister = isAllowToRegisterByTeacher or isAllowToRegisterByGrade or accessID == "studentdemo"

    if not isAllowToRegister and currentSession.Priority == 1:
        # Maybe they are on the priority list
        subq = select(func.count(PriorityEnrolling.id)).where(PriorityEnrolling.studentID == student.id)
        ans = db.session.execute(subq).scalar_one_or_none()
        if ans == 1:
            app.logger.info(f"[{accessID}] granting access, on priority list")
            isAllowToRegister = True

    if not isAllowToRegister:
        app.logger.info(f"[{accessID}] denying access, not allowed to register yet")
        return render_template("notyet.html", teacher=student.teacher, grade=student.grade, accessID=accessID)

    # A list of electives for the current session
    subq = select(SessionElective).where(SessionElective.session == currentSession)
    electives = db.session.scalars(subq).fetchall()

    isEnrolledForSession = RegistrationTools.studentEnrolledForSession(student, currentSession)
    if isEnrolledForSession:
        app.logger.info(f"{_uwsgideets()} [{accessID}] already registered, showing schedule")
        return showSchedule(student, currentSession)

    previousForm = {}
    errors = []
    if request.method == "POST":
        # Did they select enough PE?
        PE_electives = list(filter(lambda e: e.elective.consideredPE, electives))
        PE_electiveIDs = list(map(lambda e: e.id, PE_electives))

        # Did rotation=3 electives stay together (rotation1 and rotation2 need to match)
        R3_electives = list(filter(lambda e: e.rotation == 3, electives))
        R3_electiveIDs = list(map(lambda e: e.id, R3_electives))

        # Avoid back-to-back enrollment for those electives that desire it.
        # We need to find the session elective IDs for both R1 and R2 electives (they'll be different) and pair them up.
        avoidConsecutiveSignups_electives = list(filter(lambda e: e.elective.avoidConsecutiveSignups, electives))
        avoidConsecutiveSignups_R1_electives = list(filter(lambda e: e.rotation == 1, avoidConsecutiveSignups_electives))
        avoidConsecutiveSignups_pairs = {}
        for e in avoidConsecutiveSignups_electives:
            if e.rotation == 2:
                for r1_e in avoidConsecutiveSignups_R1_electives:
                    if r1_e.electiveID == e.electiveID:
                        avoidConsecutiveSignups_pairs[r1_e.id] = e.id
                        break

        studentElectivesIDs = []
        app.logger.debug(f"{_uwsgideets()} [{accessID}] request.form: {request.form}")

        # If the form errors on a class being full and the student doesn't change it, it will be resubmitted as empty and not be part
        # of the request.form contents. We are always expecting 8, so anything less is a problem.
        if len(request.form.keys()) < 8:
            # Find which ones are missing
            missing = []
            for day in ["monday", "wednesday", "thursday", "friday"]:
                for rotation in [1, 2]:
                    key = f"{day}_rotation_{rotation}"
                    if key not in request.form.keys():
                        missing.append(key)
            desc = ""
            for miss in missing:
                (day,rotation) = miss.split("_rotation_")
                if len(desc):
                    desc += ", "
                desc += f"{day.title()} R{rotation}"

            msg = f"You attempted to reselect a full elective on {desc}. This isn't valid and those entries have been reset. Please choose again."
            errors.append(msg)
            app.logger.error(f"{_uwsgideets()} [{accessID}] {msg}")
        else:
            # The web server runs multiple copies of the web app simultaneously. We need to lock this critical section so that no two (or more) processes
            # can simultaneously get currentEnrollment numbers independently of writing to the database while those enrollment numbers are considered correct.
            # Important Note: uwsgidecorators.lock does not play nicely with Flask's early returns of functions that show UI to the user.
            #                 It will continue execution from the caller regardless of what Flask did.
            @uwsgidecorators.lock
            def _runEnrollmentAttempt():
                PE_count = 0
                currentEnrollment = RegistrationTools.currentEnrollmentCounts(electives)  # the count of seats already occupied (the reason we're under the lock)

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
                            app.logger.error(f"{_uwsgideets()} [{accessID}] {msg}")

                    if esID in avoidConsecutiveSignups_pairs:
                        partnerKey = key.replace("1","2") # create the rotation 2 partner key
                        if avoidConsecutiveSignups_pairs[esID] == int(request.form[partnerKey]):
                            consecutiveSignup = list(filter(lambda e: e.id == esID, avoidConsecutiveSignups_R1_electives))[0]
                            msg = f"You cannot take <b>{consecutiveSignup.elective.name}</b> back-to-back on {consecutiveSignup.day}. Change either rotation 1 or 2 to another elective."
                            errors.append(msg)
                            app.logger.error(f"{_uwsgideets()} [{accessID}] {msg}")

                    # Did a class fill up between the form being loaded and submitted?
                    if currentEnrollment[esID]["remaining"] <= 0:
                        fullElective = list(filter(lambda e: e.id == esID, electives))[0]
                        msg = f"The class '{fullElective.elective.name}' on {fullElective.day} is now full. Please choose another elective."
                        errors.append(msg)
                        app.logger.error(f"{_uwsgideets()} [{accessID}] {msg}")

                if PE_count < 3:
                    msg = f"You need at least 3 PE electives, you currently have {PE_count}. Look for electives with 🏈."
                    errors.append(msg)
                    app.logger.error(f"{_uwsgideets()} [{accessID}] {msg}")
                elif PE_count > 4: 
                    msg = f"You can have at most 4 PE electives, you currently have {PE_count}. Choose different non-PE electives."
                    errors.append(msg)
                    app.logger.error(f"{_uwsgideets()} [{accessID}] {msg}")

                if len(studentElectivesIDs) != 8:
                    msg = f"Critical application error! Unexpected count of elective IDs <pre>{studentElectivesIDs}</pre>. (this is not an error you can fix)"
                    errors.append(msg)
                    app.logger.error(f"{_uwsgideets()} [{accessID}] {msg}")
                    app.logger.error(f"{_uwsgideets()} [{accessID}] studentElectivesIDs: {studentElectivesIDs}")

                if len(errors) > 0:
                    return("nope", "nope", []) # must return something
                else:
                    # There are no errors! We can submit their schedule and show them the good news.
                    studentElectives = list(filter(lambda e: e.id in studentElectivesIDs, electives))
                    
                    # We could have less than 8 electives chosen as rotation=3 electives will only be counted once (we will never have more than 8 though)
                    R3_electives_taken = len(list(filter(lambda x: x in studentElectivesIDs, R3_electiveIDs)))
                    if len(studentElectives) != (8 - R3_electives_taken):
                        msg = f"Critical application error! Unexpected count (expected {8 - R3_electives_taken} found {len(studentElectives)}) of student electives <pre>{studentElectives}</pre>. (this is not an error you can fix)"
                        errors.append(msg)
                        app.logger.error(f"{_uwsgideets()} [{accessID}] {msg}")
                        app.logger.error(f"{_uwsgideets()} [{accessID}] studentElectivesIDs: {studentElectivesIDs}")
                        foundNames = list(map(lambda se: f"se.id: {se.id} name: {se.elective.name}", studentElectives))
                        app.logger.error(f"{_uwsgideets()} [{accessID}] studentElectives found: {foundNames}")
                        return("nope", "nope", []) # just return something
                    else:
                        if accessID == "studentdemo":
                            (code, result) = ('ok', 'Demo account registration, not real')
                        else:
                            (code, result) = RegistrationTools.registerStudent(student, studentElectives)

                        return (code, result, studentElectives)

            # Attempt to enroll
            (code, result, studentElectives) = _runEnrollmentAttempt()

            if len(errors) > 0:
                previousForm = request.form
            else:
                if (code == "ok"):
                    return showSchedule(student, currentSession, studentElectives)
                else:
                    # Something has gone pretty wrong at this point. Database has failed to accept the addition.
                    err = f"{_uwsgideets()} [{accessID}] Failed to save results: {result}"
                    app.logger.error(err)
                    return err

        # END else: attempting to register

        # Errors gathered from POST requests not attempting to register
        if len(errors) > 0:
            previousForm = request.form

    # END if request.method == "POST":

    # Does the student already have classes enrolled? If so, those are mandatory and need to replace any options they may have.
    all_mandatory_electives = RegistrationTools.findScheduledClasses(student)
    if not all_mandatory_electives:
        all_mandatory_electives = [] # if there's no scheduled classes, make the filter happy


    def _findMandatoryElectives(day, electives):
        r1 = list(filter(lambda e: e.day == day and e.rotation == 1, electives))
        r2 = list(filter(lambda e: e.day == day and e.rotation == 2, electives))
        r3 = list(filter(lambda e: e.day == day and e.rotation == 3, electives))
        return (r1, r2, r3)

    def _findChoosableElectives(day, rotation, electives, session):
        fileredElectives = list(filter(lambda e: e.day == day and e.rotation == rotation and e.elective.assignOnly == False, electives))
        if session.number % 2 == 0:
            fileredElectives = list(filter(lambda e: e.elective.multisession == False, fileredElectives))

        # TODO - jimt - Would be nice if the classes were ordered alphabetically
        return fileredElectives

    def _availableElectives(day, allElectives, mandatoryElectives, session):
        r1 = r2 = r3 = []
        (r1_mandatory, r2_mandatory, r3_mandatory) = _findMandatoryElectives(day, mandatoryElectives)
        if len(r1_mandatory):
            r1 = r1_mandatory
        else:
            if len(r3_mandatory) == 0:
                r1 = _findChoosableElectives(day, 1, allElectives, session)

        if len(r2_mandatory):
            r2 = r2_mandatory
        else:
            if len(r3_mandatory) == 0:
                r2 = _findChoosableElectives(day, 2, allElectives, session)

        if len(r3_mandatory):
            r3 = r3_mandatory
        else:
            if len(r1_mandatory) == 0 and len(r2_mandatory) == 0:
                r3 = _findChoosableElectives(day, 3, allElectives, session)

        return(r1, r2, r3)

    (mon_r1, mon_r2, mon_r3) = _availableElectives("Monday", electives, all_mandatory_electives, currentSession)
    (wed_r1, wed_r2, wed_r3) = _availableElectives("Wednesday", electives, all_mandatory_electives, currentSession)
    (thu_r1, thu_r2, thu_r3) = _availableElectives("Thursday", electives, all_mandatory_electives, currentSession)
    (fri_r1, fri_r2, fri_r3) = _availableElectives("Friday", electives, all_mandatory_electives, currentSession)

    classJSONPath = os.path.join(os.path.dirname(app.instance_path), "electives/classes.json")
    electiveDescriptions = ""
    with open(classJSONPath, 'r', encoding='utf-8') as f:
        electiveDescriptions = json.load(f)
    electiveDescriptions = sorted(electiveDescriptions, key=lambda d: d['v'])

    # Find previous schedules so we can show them what they took "the last time" (which they all forget).
    session1 = session2 = session3 = None
    if currentSession.number > 1:
        def _findPreviousSchedule(sessionNumber):
            q = select(Session).where(Session.number == sessionNumber)
            previousSession = db.session.execute(q).scalar_one_or_none()
            previousElectives = RegistrationTools.chosenElectivesForSessions(student, previousSession)

            # If a student is added late in the year, they won't have any previousElectives and the indexing here will blow up.
            if len(previousElectives) == 0:
                return dict()
            
            previous = dict(mon_r1 = list(filter(lambda e: e.day == "Monday" and e.rotation in [1,3], previousElectives))[0],
                            wed_r1 = list(filter(lambda e: e.day == "Wednesday" and e.rotation in [1,3], previousElectives))[0],
                            thu_r1 = list(filter(lambda e: e.day == "Thursday" and e.rotation in [1,3], previousElectives))[0],
                            fri_r1 = list(filter(lambda e: e.day == "Friday" and e.rotation in [1,3], previousElectives))[0],
                            mon_r2 = list(filter(lambda e: e.day == "Monday" and e.rotation in [2,3], previousElectives))[0],
                            wed_r2 = list(filter(lambda e: e.day == "Wednesday" and e.rotation in [2,3], previousElectives))[0],
                            thu_r2 = list(filter(lambda e: e.day == "Thursday" and e.rotation in [2,3], previousElectives))[0],
                            fri_r2 = list(filter(lambda e: e.day == "Friday" and e.rotation in [2,3], previousElectives))[0])
            return previous

        if currentSession.number >= 2:
            session1 = _findPreviousSchedule(1)
        if currentSession.number >= 3:
            session2 = _findPreviousSchedule(2)
        if currentSession.number >= 4:
            session3 = _findPreviousSchedule(3)

    # Always re-query for currentEnrollment if the attempt to register above failed.
    # This is also how we get currentEnrollment for GET requests. 
    # Calling this as late as possible to ensure the most up-to-date info in the form
    currentEnrollment = RegistrationTools.currentEnrollmentCounts(electives)

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
                                                electiveDescriptions=electiveDescriptions,
                                                session1=session1,
                                                session2=session2,
                                                session3=session3
                                                )

@app.route("/_admin_", methods=['GET', 'POST'])
def adminPage():
    if request.method == "POST":
        if request.form["formID"] == "two_session_assignments":
            sessionNumber = int(request.form["sessionNumber"])
            prev_sessionNumber = sessionNumber - 1
            s = select(Student.name.label("student_name"), SessionElective.day, SessionElective.rotation, Elective.name.label("elective_name")) \
                            .select_from(Student) \
                            .join(Schedule).where(Schedule.studentID == Student.id) \
                            .join(SessionElective).where(SessionElective.sessionID == Session.id) \
                            .join(Session).where(Session.number == prev_sessionNumber) \
                            .join(Elective).where(Elective.id == SessionElective.electiveID) \
                                            .where(or_(Elective.multisession == True,
                                                        Elective.name == "RSP/Homework Help")) \
                            .order_by(Student.name)
            records = db.session.execute(s).fetchall()

            fileBuffer = io.StringIO()
            w = csv.writer(fileBuffer, quoting=csv.QUOTE_ALL)
            w.writerow(["student", "rotation", "Monday", "Wednesday", "Thursday", "Friday"])

            def _writeRow(studentName, rotation, v):
                if all(value == "" for value in v.values()) == False:
                    w.writerow([studentName, rotation, v["Monday"], v["Wednesday"], v["Thursday"], v["Friday"]])

            currentStudentName = None
            r1 = r2 = r3 = dict()
            for r in records:
                if currentStudentName != r.student_name:
                    if currentStudentName != None:
                        # Write out the student to the CSV
                        _writeRow(currentStudentName, "1", r1)
                        _writeRow(currentStudentName, "2", r2)
                        _writeRow(currentStudentName, "3", r3)
                    currentStudentName = r.student_name
                    r1 = dict(Monday="", Wednesday="", Thursday="", Friday="")
                    r2 = dict(Monday="", Wednesday="", Thursday="", Friday="")
                    r3 = dict(Monday="", Wednesday="", Thursday="", Friday="")
                
                if r.rotation == 1:
                    r1[r.day] = r.elective_name
                elif r.rotation == 2:
                    r2[r.day] = r.elective_name
                elif r.rotation == 3:
                    r3[r.day] = r.elective_name

            # Write out the last student we found (sorry Willa)
            _writeRow(currentStudentName, "1", r1)
            _writeRow(currentStudentName, "2", r2)
            _writeRow(currentStudentName, "3", r3)

            return Response(fileBuffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition":f"attachment;filename=Session #{sessionNumber} two-session electives input.csv"})

        elif request.form["formID"] == "start_session":
            sessionNumber = int(request.form["sessionNumber"])
            currentSession = RegistrationTools.activeSession()

            if currentSession.number != sessionNumber:
                currentSession = RegistrationTools.setActiveSession(sessionNumber)

            columns = ["Bishop", "Ruiz", "Paolini", "sixthGrade", "seventhGrade", "eigthGrade", "Priority"]
            for sessionNum in range(1,5):
                active = request.form.getlist(f"session_{sessionNum}_active")
                sessionRecord = db.session.execute(select(Session).where(Session.number == sessionNum)).scalar_one_or_none()
                # Clear all the values
                for column_name in columns:
                    setattr(sessionRecord, column_name, 0)
                # Set the new values
                for column_name in active:
                    setattr(sessionRecord, column_name, 1)
                db.session.commit()

            flash(f"Updated session info", "ok")
            return redirect(request.url)

        elif request.form["formID"] == "modify_elective_assignment":
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

        elif request.form["formID"] == "elective_schedules":
            currentSession = RegistrationTools.activeSession()

            includeSeatCount = True if "includeSeatsRemaining" in request.form and request.form["includeSeatsRemaining"] == "on" else False
            includeAssignOnly = True if "includeAssignOnly" in request.form and request.form["includeAssignOnly"] == "on" else False

            # We want the option to both find and exclude the "assign only" classes (usually RSP, but there's been others)
            # Default to not showing assign only unless the form indicates we should. Having two False in the array is fine.
            assignOnlyOptions = [False]
            assignOnlyOptions.append(includeAssignOnly)

            allR1 = [["Rotation 1"]]
            allR2 = [["Rotation 2"]]

            for day in ["Monday", "Wednesday", "Thursday", "Friday"]:
                r1 = []
                r2 = []
                subq = select(SessionElective).join(Elective).where(SessionElective.electiveID == Elective.id)\
                                                                                            .where(Elective.assignOnly.in_(assignOnlyOptions))\
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


        elif request.form["formID"] == "enrollment_overview":
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

        elif request.form["formID"] == "csv_schedules":
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
        
        elif request.form["formID"] == "session_upload":
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


        elif request.form["formID"] == "roster_upload":
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

        elif request.form["formID"] == "priority_assignment":
            if 'priorities' not in request.files:
                flash("No priorities file found", 'error')
                return redirect(request.url)

            priorities = request.files['priorities']
            if priorities.filename == '':
                flash("No selected file", 'error')
                return redirect(request.url)
            
            priorities = map(lambda x: str(x, 'utf-8'), priorities)
            (code, result) = ConfigUtils.assignPriorityEnrollment(priorities)
            flash(result, code)
            return redirect(request.url)

        elif request.form["formID"] == "modify_classes_json":
            if 'classes_dot_json' not in request.files:
                flash("No classes.json file found", 'error')
                return redirect(request.url)

            classes_dot_json = request.files['classes_dot_json']
            if classes_dot_json.filename == '':
                flash("No selected file", 'error')
                return redirect(request.url)

            classes = json.load(classes_dot_json)
            updatedClasses = []
            for kls in classes:
                className = kls['v']
                currentSession = RegistrationTools.activeSession()
                subq = select(SessionElective)\
                                            .join(Elective).where(SessionElective.electiveID == Elective.id)\
                                                            .where(Elective.name == className)\
                                            .join(Session).where(SessionElective.session == currentSession).order_by(SessionElective.rotation)
                electives = db.session.scalars(subq).fetchall()
                desc = "("
                for count,e in enumerate(electives):
                    if e.rotation == 3:
                        desc += f"{e.day}, both rotations 1:05-2:35"
                    else:
                        preamble = f"{e.day}," if count == 0 else " and"
                        desc += f"{preamble} R{e.rotation}"
                        if e.rotation == 1:
                            desc += " 1:05-1:50"
                        else:
                            desc += " 1:50-2:35"
                desc += ")"
                kls['schedule'] = desc
                updatedClasses.append(kls)
            
            jsonBuffer = io.StringIO(json.dumps(updatedClasses, indent=4))
            return Response(jsonBuffer.getvalue(), mimetype="application/json", headers={"Content-Disposition":f"attachment;filename=classes.json"})

        elif request.form["formID"] == "reset_database":
            (code, result) = ConfigUtils.resetDatabase()
            flash(result, code)
            return redirect(request.url)

        else:
            flash("Unknown formID", 'error')
            return redirect(request.url)
    else: ## request.method == "GET"
        studentCount = db.session.query(func.count(Student.id)).scalar()
        students = db.session.scalars(select(Student).order_by(Student.name)).fetchall()
        sessions = db.session.scalars(select(Session)).fetchall()

        return render_template('admin.html', studentCount=studentCount, students=students, sessions=sessions)

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
    
    if task == "student_access_key":
        studentID = request.args.get("sID")
        student = db.session.execute(select(Student).where(Student.id == studentID)).scalar_one_or_none()
        if not student:
            return jsonify({'error':'Unknown student ID'})

        return jsonify({'key': student.accessID})

    # Comes from the admin "modify assignments" page
    elif task == "student_assignments":
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

    elif task == "log":
        accessID = request.args.get("accessID")
        msg = request.args.get("msg")
        app.logger.info(f"[{accessID}] {msg}")
        return jsonify()

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

    studentSchedule = dict(mon_r1 = list(filter(lambda e: e.day == "Monday" and e.rotation in [1,3], electives))[0],
                           wed_r1 = list(filter(lambda e: e.day == "Wednesday" and e.rotation in [1,3], electives))[0],
                           thu_r1 = list(filter(lambda e: e.day == "Thursday" and e.rotation in [1,3], electives))[0],
                           fri_r1 = list(filter(lambda e: e.day == "Friday" and e.rotation in [1,3], electives))[0],
                           mon_r2 = list(filter(lambda e: e.day == "Monday" and e.rotation in [2,3], electives))[0],
                           wed_r2 = list(filter(lambda e: e.day == "Wednesday" and e.rotation in [2,3], electives))[0],
                           thu_r2 = list(filter(lambda e: e.day == "Thursday" and e.rotation in [2,3], electives))[0],
                           fri_r2 = list(filter(lambda e: e.day == "Friday" and e.rotation in [2,3], electives))[0])

    return render_template('schedule.html', student=student, session=session, studentSchedule=studentSchedule)

# This is a test route to verify that critical section locking works as expected. You can call this
# many times concurrently and pass different values, each value will have the function wait for that 
# many seconds. For a two-process setup (which is the default on PythonAnywhere) you should see two
# of your requests get serviced right away while additional ones wait for one of those to finish. 
# And the ones in flight should not print "yo... sup?" until they are done.
# You'll need to be looking at the server log files to see the output of the print() statement.
# A good command line test is:
# URL="http://127.0.0.1:5000/test_locks"; curl ${URL}/10 & curl ${URL}/2 & curl ${URL}/5 &
@app.route("/test_locks/<passedWaitTime>")
def test_locks(passedWaitTime=None):
    print(f"{_uwsgideets()} passedWaitTime called with {passedWaitTime}")

    @uwsgidecorators.lock
    def _callTheFunc(waitFor):
        print(f"{_uwsgideets()} _callTheFunc called")
        time.sleep(waitFor)
        return f"<p>Yo... sup? waited for: {waitFor} </p>\n"

    return _callTheFunc(int(passedWaitTime))

# A good set of command lines for this set of tests:
#  curl http://127.0.0.1:5000/set_test
#  for x in `seq 1 10`; do curl http://127.0.0.1:5000/run_test & done
@app.route("/set_test")
def set_test():
    with open("./test.txt", 'w', encoding='utf-8') as f:
        f.write("1")
    return "test reset to 1\n"

@app.route("/run_test")
def run_test():
    
    @uwsgidecorators.lock
    def _internalFunc():
        with open("./test.txt", 'r', encoding='utf-8') as f:
            value = f.read()
        
        newValue = int(value) + 1
        print(f"{_uwsgideets()} old value: {value} newValue: {newValue}")
        
        with open("./test.txt", 'w', encoding='utf-8') as f:
            f.write(str(newValue))

    _internalFunc()
    return "ok"

def _uwsgideets():
    # returns Worker and Request IDs for the uwsgi process that's executing the app
    return f"[wkr/req {uwsgi.worker_id()}/{uwsgi.request_id()}]"

# This builds a per-day (or all days, if you ask for it) schedule suitable for printing. You can also download CSVs of these.
@app.route("/session_schedules/<targetDay>")
@app.route("/session_schedules/<targetDay>/<passkey>")
def session_schedules(targetDay="all", passkey=""):
    currentSession = RegistrationTools.activeSession()

    # Some classes's enrollments are available only to teachers (RSP, Gender and Sexuality Alliance, etc) so this is the way we can allow
    # teachers to see those schedules at the same time not showing them to other parents. The hex value below can be anything you want
    # it's just the output of the following:
    #       python3 -c 'import hashlib;print(hashlib.md5("thesecretkey".encode()).hexdigest())'
    #         -or-
    #       md5 -s "thesecretkey"
    # where "thesecretkey" is what you want the teachers to be adding to the URL, e.g.,
    #       https://***REMOVED***.pythonanywhere.com/session_schedules/thursday/thesecretkey
    # 
    # The database has a boolean field "hideFromSessionSchedules" which controls if the elective is viewable here or not. "assignOnly" is 
    # not this field, that is for electives that should not be allowed to be generally selectable.
    #
    # Note: the passkey must be all lower-case. It can contain numbers, dashes, or underscores, but all lower-case letters.
    passkeyIsCorrect = (hashlib.md5(passkey.encode()).hexdigest() == "5427040c313c735f56be5cfb833d89e6")
    filterArgs = [0]
    if passkeyIsCorrect:
        filterArgs.append(1)

    days = ["Monday", "Wednesday", "Thursday", "Friday"]
    if targetDay != "all":
        titledTargetDay = str.title(targetDay)
        if titledTargetDay in days:
            days = [titledTargetDay]

    dayContainers = {}
    for day in days:
        dayContainer = []
        for rotation in [[1,3], [2,3]]:
            container = []
            electiveNames = []
            electiveAttendees = []

            subq = select(SessionElective).where(SessionElective.day == day).where(SessionElective.rotation.in_(rotation))\
                                        .join(Elective).where(SessionElective.electiveID == Elective.id)\
                                        .filter(Elective.hideFromSessionSchedules.in_(filterArgs))\
                                        .join(Session).where(SessionElective.session == currentSession).order_by(Elective.name)
            sessionElectivesForDay = db.session.scalars(subq).fetchall()
            for se in sessionElectivesForDay:
                electiveNames.append(f"{se.elective.name}|{se.elective.room}|{se.elective.lead}")
                subq = select(Student.name).select_from(Schedule).where(Schedule.sessionElectiveID == se.id)\
                                                                 .join(Student).where(Schedule.studentID == Student.id).order_by(Student.name)
                students = db.session.scalars(subq).fetchall()
                electiveAttendees.append(students)

            container.append([f"{day}|Rotation {rotation[0]}|" + ("1:05-1:50" if rotation[0] == 1 else "1:50-2:35")])
            container.append(electiveNames)
            zl = zip_longest(*electiveAttendees, fillvalue="")
            for z in zl:
                container.append(z)
            dayContainer.append(container)
        
        dayContainers[day] = dayContainer

    return render_template('assigned_schedules_view.html', sessionNumber=currentSession.number,
                                                           monday=dayContainers["Monday"] if "Monday" in dayContainers else None, 
                                                           wednesday=dayContainers["Wednesday"] if "Wednesday" in dayContainers else None,
                                                           thursday=dayContainers["Thursday"] if "Thursday" in dayContainers else None,
                                                           friday=dayContainers["Friday"] if "Friday" in dayContainers else None
                                                           )

# If you uncomment this, you can execute code at startup of the server on the command line. Helpful to sort out syntax, SQL queries, and Jinja template bugs
# with app.app_context():
#     currentSession = RegistrationTools.activeSession()

#     day = "Monday"
#     rotation = [1,3]
#     filterArgs = [0]
#     subq = select(SessionElective).where(SessionElective.day == day).where(SessionElective.rotation.in_(rotation))\
#                                 .join(Elective).where(SessionElective.electiveID == Elective.id)\
#                                 .filter(Elective.assignOnly.in_(filterArgs))\
#                                 .join(Session).where(SessionElective.session == currentSession).order_by(Elective.name)
#     sessionElectivesForDay = db.session.scalars(subq).fetchall()
#     electiveNames = list(map(lambda se: se.elective.name, sessionElectivesForDay))
#     print(electiveNames)
#     pdb.set_trace()

#     subq = select(SessionElective)\
#                                 .join(Elective).where(SessionElective.electiveID == Elective.id)\
#                                                 .where(Elective.name == "K/1st Enrichment Assistant")\
#                                 .join(Session).where(SessionElective.session == currentSession).order_by(SessionElective.rotation)
#     chessElective = db.session.scalars(subq).fetchall()
#     pdb.set_trace()
#     print("what")


#     print(app.jinja_env)
#     print(app.jinja_env.get_template('schedule.html'))
#     s = select(Student.name.label("student_name"), SessionElective.day, SessionElective.rotation, Elective.name) \
#                        .select_from(Student) \
#                        .join(Schedule).where(Schedule.studentID == Student.id) \
#                        .join(SessionElective).where(SessionElective.sessionID == 1) \
#                        .join(Elective).where(Elective.id == SessionElective.electiveID) \
#                                       .where(or_(Elective.multisession == True,
#                                                  Elective.name == "RSP/Homework Help")) \
#                        .order_by(Student.name)
#     records = db.session.execute(s).fetchall()

