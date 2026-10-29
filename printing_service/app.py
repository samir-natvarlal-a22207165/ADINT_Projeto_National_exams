import io
import os
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, send_file, url_for
from flask_xmlrpcre.xmlrpcre import Fault, XMLRPCHandler

from models import PrintJob, ResolutionSheet, db
from pdf_utils import build_resolution_pdf, fit_course

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_PDF = os.path.join(BASE_DIR, "Exam-template.pdf")

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-printing-service"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "printing.sqlite")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()

handler = XMLRPCHandler("api")
handler.connect(app, "/api")


# AD_3 (XML-RPC) - called by the Admin Service, see the contract in admin_service/app.py
@handler.register
def print_resolution_sheets(exam_id, course, date, n_students):
    if n_students <= 0:
        raise Fault(1, "n_students must be positive")
    if db.session.get(PrintJob, exam_id) is not None:
        raise Fault(2, "exam %d was already printed" % exam_id)
    try:
        exam_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise Fault(3, "date must be in the format YYYY-MM-DD")

    job = PrintJob(exam_id=exam_id, course=course, date=exam_date, pdf_file=b"")
    for number in range(1, n_students + 1):
        job.sheets.append(ResolutionSheet(sheet_number=number))
    db.session.add(job)
    db.session.flush()  # assigns the sheet ids

    # long course names are shortened so the title fits on one line
    suffix = " - %s - Exam %d - Sheet %%d" % (date, exam_id)
    try:
        short_course = fit_course(TEMPLATE_PDF, course, suffix % n_students)
        job.pdf_file = build_resolution_pdf(
            TEMPLATE_PDF, [(s.id, short_course + suffix % s.sheet_number) for s in job.sheets]
        )
    except ValueError as e:
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
    job = db.get_or_404(PrintJob, exam_id)
    return render_template("sheets.html", job=job)


@app.route("/exams/<int:exam_id>/sheets.pdf")
def download_sheets(exam_id):
    job = db.get_or_404(PrintJob, exam_id)
    return send_file(
        io.BytesIO(job.pdf_file),
        mimetype="application/pdf",
        download_name="exam-%d-sheets.pdf" % exam_id,
    )


# JSON endpoint for the other services
@app.route("/api/exams/<int:exam_id>/sheets")
def api_sheets(exam_id):
    job = db.session.get(PrintJob, exam_id)
    if job is None:
        return jsonify({"error": "not found"}), 404
    return jsonify([s.id for s in job.sheets])


if __name__ == "__main__":
    app.run(port=5003, debug=True)
