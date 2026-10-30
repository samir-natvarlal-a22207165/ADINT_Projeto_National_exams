import io
import os
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, send_file, url_for
from flask_xmlrpcre.xmlrpcre import Fault, XMLRPCHandler

from models import PrintJob, ResolutionSheet, db
from pdf_utils import build_resolution_pdf
from utils import BoundedIntConverter

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_PDF = os.path.join(BASE_DIR, "Exam-template.pdf")

# Name used in the PDF file name when the user that ordered the printing is not known.
ORDERED_BY_UNKNOWN = "unknown"


app = Flask(__name__)
app.url_map.converters["int"] = BoundedIntConverter
app.config["SECRET_KEY"] = "dev-printing-service"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "printing.sqlite")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()

handler = XMLRPCHandler("api")
handler.connect(app, "/api")


def is_int(value):
    # bool is a subclass of int in Python, but True/False are not identifiers
    return isinstance(value, int) and not isinstance(value, bool)


# AD_3 (XML-RPC) - called by the Admin Service, see the contract in admin_service/app.py
@handler.register
def print_resolution_sheets(exam_id, course, date, n_students, ordered_by):
    if not (
        is_int(exam_id)
        and isinstance(course, str)
        and isinstance(date, str)
        and is_int(n_students)
        and (is_int(ordered_by) or ordered_by == "")
    ):
        raise Fault(6, "wrong argument types: expected (int, str, str, int, int or \"\")")
    if n_students <= 0:
        raise Fault(1, "n_students must be positive")
    if PrintJob.query.filter(PrintJob.exam_id == exam_id).first() is not None:
        raise Fault(2, "exam %d was already printed" % exam_id)
    try:
        exam_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise Fault(3, "date must be in the format YYYY-MM-DD")
    if ordered_by != "" and ordered_by <= 0:
        raise Fault(5, "ordered_by must be a positive user identifier")

    now = datetime.now()
    filename = "exam-%d_%s_user-%s.pdf" % (
        exam_id, now.strftime("%Y%m%d-%H%M%S"), ordered_by if ordered_by != "" else ORDERED_BY_UNKNOWN
    )
    job = PrintJob(
        exam_id=exam_id, course=course, date=exam_date, created_at=now,
        filename=filename, pdf_file=b"",
    )
    for number in range(1, n_students + 1):
        job.sheets.append(ResolutionSheet(sheet_number=number))
    db.session.add(job)
    db.session.flush()  # assigns the sheet ids

    # the title (course, date, page) is the same for every sheet; the QR code has the sheet id
    try:
        job.pdf_file = build_resolution_pdf(TEMPLATE_PDF, [s.id for s in job.sheets], course, date)
    except ValueError as e:
        db.session.rollback()
        raise Fault(4, "could not build the resolution sheets: %s" % e)
    db.session.commit()
    return {"exam_id": exam_id, "n_sheets": n_students}


@app.route("/")
def index():
    return redirect(url_for("list_exams"))


# Exams that already have resolution sheets
@app.route("/exams")
def list_exams():
    jobs = PrintJob.query.order_by(PrintJob.date, PrintJob.exam_id).all()
    return render_template("exams.html", jobs=jobs)


@app.route("/exams/<int:exam_id>/sheets")
def list_sheets(exam_id):
    job = PrintJob.query.filter(PrintJob.exam_id == exam_id).first_or_404()
    return render_template("sheets.html", job=job)


@app.route("/exams/<int:exam_id>/sheets.pdf")
def download_sheets(exam_id):
    job = PrintJob.query.filter(PrintJob.exam_id == exam_id).first_or_404()
    return send_file(
        io.BytesIO(job.pdf_file),
        mimetype="application/pdf",
        download_name=job.filename,
    )


# JSON endpoint for other services
@app.route("/api/exams/<int:exam_id>/sheets")
def api_sheets(exam_id):
    job = PrintJob.query.filter(PrintJob.exam_id == exam_id).first()
    if job is None:
        return jsonify({"error": "not found"}), 404
    return jsonify([s.id for s in job.sheets])


if __name__ == "__main__":
    app.run(port=5003, debug=True)
