import csv
import io
import os
import xmlrpc.client
from datetime import datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from models import Enrollment, Exam, db

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Where the Printing Service exposes its XML-RPC endpoint (see the contract below).
PRINTING_URL = os.environ.get("PRINTING_URL", "http://127.0.0.1:5003/api")

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-admin-service"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "admin.sqlite")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()


def parse_positive_int(raw):
    raw = (raw or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError("'%s' is not a positive integer" % raw)
    return int(raw)


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
                date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("date must be in the format YYYY-MM-DD")
        except ValueError as e:
            flash(str(e), "error")
        else:
            exam = Exam(course=course, date=date)
            db.session.add(exam)
            db.session.commit()
            flash("Exam %d (%s, %s) scheduled." % (exam.id, exam.course, exam.date), "ok")
            return redirect(url_for("list_exams"))
    return render_template("schedule_exam.html")


# AD_2 - bulk enroll students in an exam from a CSV file with a student_id column
@app.route("/exams/<int:exam_id>/enroll", methods=["GET", "POST"])
def enroll_students(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    result = {}
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Choose a CSV file.", "error")
            return render_template("enroll.html", exam=exam, **result)
        try:
            text = file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("File must be UTF-8 encoded.", "error")
            return render_template("enroll.html", exam=exam, **result)

        reader = csv.DictReader(io.StringIO(text))
        reader.fieldnames = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
        if "student_id" not in reader.fieldnames:
            flash("Missing CSV column: student_id", "error")
            return render_template("enroll.html", exam=exam, **result)

        already = {e.student_id for e in exam.enrollments}
        added, duplicates, errors = 0, 0, []
        for line_no, row in enumerate(reader, start=2):
            try:
                student_id = parse_positive_int(row.get("student_id"))
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
#                           n_students: int) -> {"exam_id": int, "n_sheets": int}
#
# Sheets are anonymous, so no student identifiers are sent, only how many are needed.
@app.route("/exams/<int:exam_id>/print", methods=["POST"])
def order_printing(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    n_students = len(exam.enrollments)
    if exam.printing_ordered:
        flash("Printing for exam %d was already ordered." % exam.id, "error")
    elif n_students == 0:
        flash("Enroll students before ordering the printing.", "error")
    else:
        try:
            printing = xmlrpc.client.ServerProxy(PRINTING_URL)
            reply = printing.print_resolution_sheets(
                exam.id, exam.course, exam.date.isoformat(), n_students
            )
        except (OSError, xmlrpc.client.Fault, xmlrpc.client.ProtocolError) as e:
            flash("Printing Service call failed: %s" % e, "error")
        else:
            exam.printing_ordered = True
            db.session.commit()
            flash(
                "Printing ordered for exam %d: %s sheet(s)." % (exam.id, reply.get("n_sheets", n_students)),
                "ok",
            )
    return redirect(url_for("list_exams"))


# ST_1 - information about the exams a student is enrolled in
@app.route("/students")
def student_lookup():
    raw = request.args.get("student_id")
    if raw is not None:
        try:
            return redirect(url_for("student_exams", student_id=parse_positive_int(raw)))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("student_lookup.html")


@app.route("/students/<int:student_id>/exams")
def student_exams(student_id):
    exams = (
        Exam.query.join(Enrollment, Enrollment.exam_id == Exam.id)
        .filter(Enrollment.student_id == student_id)
        .order_by(Exam.date, Exam.id)
        .all()
    )
    return render_template("student_exams.html", student_id=student_id, exams=exams)


# JSON endpoints for the other services
@app.route("/api/exams")
def api_exams():
    return jsonify([e.to_dict() for e in Exam.query.order_by(Exam.id).all()])


@app.route("/api/exams/<int:exam_id>")
def api_exam(exam_id):
    exam = db.session.get(Exam, exam_id)
    if exam is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(exam.to_dict())


@app.route("/api/exams/<int:exam_id>/students")
def api_exam_students(exam_id):
    exam = db.session.get(Exam, exam_id)
    if exam is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(sorted(e.student_id for e in exam.enrollments))


if __name__ == "__main__":
    app.run(port=5002, debug=True)
