import os
import xmlrpc.client
from datetime import date, datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from models import Enrollment, Exam, db
from utils import BoundedIntConverter, parse_positive_int, read_csv_upload

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Where the Printing Service exposes its XML-RPC endpoint (see the contract below).
PRINTING_URL = os.environ.get("PRINTING_URL", "http://127.0.0.1:5003/api")

app = Flask(__name__)
app.url_map.converters["int"] = BoundedIntConverter
app.config["SECRET_KEY"] = "dev-admin-service"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "admin.sqlite")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()


@app.route("/")
def index():
    return redirect(url_for("list_exams"))


# List scheduled exams
@app.route("/exams")
def list_exams():
    exams = Exam.query.order_by(Exam.date, Exam.id).all()
    return render_template("exams.html", exams=exams)


# AD_1 - schedule an exam
@app.route("/exams/schedule", methods=["GET", "POST"])
def schedule_exam():
    if request.method == "POST":
        course = (request.form.get("course") or "").strip()
        raw_date = (request.form.get("date") or "").strip()
        try:
            if not course:
                raise ValueError("course is required")
            try:
                exam_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("date must be in the format YYYY-MM-DD")
            if exam_date < date.today():
                raise ValueError("date must not be in the past")
        except ValueError as e:
            flash(str(e), "error")
        else:
            exam = Exam(course=course, date=exam_date)
            db.session.add(exam)
            db.session.commit()
            flash("Exam %d (%s, %s) scheduled." % (exam.id, exam.course, exam.date), "ok")
            return redirect(url_for("list_exams"))
    return render_template("schedule_exam.html")


# AD_2 - bulk enroll students in an exam from a CSV file with a student_id column
@app.route("/exams/<int:exam_id>/enroll", methods=["GET", "POST"])
def enroll_students(exam_id):
    exam = Exam.query.filter(Exam.id == exam_id).first_or_404()
    result = {}
    if request.method == "POST":
        # the sheets were printed for the students enrolled at that moment,
        # so the enrollment list is locked once the printing is ordered
        if exam.printing_ordered:
            flash("Exam %d is locked: the printing was already ordered." % exam.id, "error")
            return render_template("enroll.html", exam=exam)
        try:
            reader = read_csv_upload(request.files.get("file"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("enroll.html", exam=exam)
        if "student_id" not in reader.fieldnames:
            flash("Missing CSV column: student_id", "error")
            return render_template("enroll.html", exam=exam)

        already = {e.student_id for e in exam.enrollments}
        added, duplicates, errors = 0, 0, []
        for line_no, row in enumerate(reader, start=2):
            try:
                student_id = parse_positive_int(row.get("student_id"), "student_id")
            except ValueError as e:
                errors.append("line %d: %s" % (line_no, e))
                continue
            if student_id in already:
                duplicates += 1
                continue
            already.add(student_id)
            db.session.add(Enrollment(exam_id=exam.id, student_id=student_id))
            added += 1
        db.session.commit()
        result = {"added": added, "duplicates": duplicates, "errors": errors}
    return render_template("enroll.html", exam=exam, **result)


# AD_3 - order the printing of the resolution sheets (XML-RPC call to the Printing Service)
#
# XML-RPC contract the Printing Service must implement (endpoint PRINTING_URL):
#
#   print_resolution_sheets(exam_id: int, course: str, date: str "YYYY-MM-DD",
#                           n_students: int, ordered_by: int or "")
#                           -> {"exam_id": int, "n_sheets": int}
#
# Sheets are anonymous, so no student identifiers are sent, only how many are needed.
# ordered_by is the identifier of the user that ordered the printing, or "" when it
# is not known (it ends up in the name of the PDF). Fault code 2 means the exam was
# already printed.
PRINTING_ALREADY_PRINTED = 2
ORDERED_BY_UNKNOWN = ""


@app.route("/exams/<int:exam_id>/print", methods=["POST"])
def order_printing(exam_id):
    exam = Exam.query.filter(Exam.id == exam_id).first_or_404()
    n_students = len(exam.enrollments)

    if exam.printing_ordered:
        flash("Printing for exam %d was already ordered." % exam.id, "error")
    elif n_students == 0:
        flash("Enroll students before ordering the printing.", "error")
    else:
        try:
            printing = xmlrpc.client.ServerProxy(PRINTING_URL)
            reply = printing.print_resolution_sheets(
                exam.id, exam.course, exam.date.isoformat(), n_students, ORDERED_BY_UNKNOWN
            )
        except xmlrpc.client.Fault as e:
            if e.faultCode == PRINTING_ALREADY_PRINTED:
                # the Printing Service has the sheets but this service lost track of it
                exam.printing_ordered = True
                db.session.commit()
                flash("Printing for exam %d had already been ordered." % exam.id, "ok")
            else:
                flash("Printing Service call failed: %s" % e.faultString, "error")
        except (OSError, xmlrpc.client.ProtocolError) as e:
            flash("Printing Service call failed: %s" % e, "error")
        else:
            exam.printing_ordered = True
            db.session.commit()
            flash(
                "Printing ordered for exam %d: %s sheet(s)." % (exam.id, reply.get("n_sheets", n_students)),
                "ok",
            )
    return redirect(url_for("list_exams"))


# ST_1 - enrollments of every student in every exam, optionally narrowed by student and course
@app.route("/students")
def enrollments():
    by = "id" if request.args.get("by") == "id" else "choose"
    raw = request.args.get("student_typed" if by == "id" else "student_choice")
    student_id = None
    if raw:
        try:
            student_id = parse_positive_int(raw, "student identifier")
        except ValueError as e:
            flash(str(e), "error")
    course = request.args.get("course") or None

    query = (
        db.session.query(Enrollment, Exam)
        .join(Exam, Enrollment.exam_id == Exam.id)
        .order_by(Exam.date, Exam.id, Enrollment.student_id)
    )
    if student_id is not None:
        query = query.filter(Enrollment.student_id == student_id)
    if course is not None:
        query = query.filter(Exam.course == course)

    students = [s for (s,) in db.session.query(Enrollment.student_id).distinct().order_by(Enrollment.student_id)]
    courses = [c for (c,) in db.session.query(Exam.course).distinct().order_by(Exam.course)]
    return render_template(
        "enrollments.html",
        rows=query.all(),
        students=students,
        courses=courses,
        by=by,
        student_id=student_id,
        course=course,
    )


@app.route("/exams/<int:exam_id>/students/<int:student_id>/unenroll", methods=["POST"])
def unenroll(exam_id, student_id):
    enrollment = Enrollment.query.filter(
        Enrollment.exam_id == exam_id, Enrollment.student_id == student_id
    ).first_or_404()
    if enrollment.exam.printing_ordered:
        flash("Exam %d is locked: the printing was already ordered." % exam_id, "error")
    else:
        db.session.delete(enrollment)
        db.session.commit()
        flash("Student %d unenrolled from exam %d." % (student_id, exam_id), "ok")
    return redirect(request.referrer or url_for("enrollments"))


# JSON endpoints for other services
@app.route("/api/exams")
def api_exams():
    return jsonify([e.to_dict() for e in Exam.query.order_by(Exam.id).all()])


@app.route("/api/exams/<int:exam_id>")
def api_exam(exam_id):
    exam = Exam.query.filter(Exam.id == exam_id).first()
    if exam is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(exam.to_dict())


@app.route("/api/exams/<int:exam_id>/students")
def api_exam_students(exam_id):
    exam = Exam.query.filter(Exam.id == exam_id).first()
    if exam is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(sorted(e.student_id for e in exam.enrollments))


if __name__ == "__main__":
    app.run(port=5002, debug=True)
