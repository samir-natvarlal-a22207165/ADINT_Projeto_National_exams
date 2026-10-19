import io
import os

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy.exc import IntegrityError

from models import ExamCorrectionPdf, ProfessorAssignment, QuestionCorrection, db
from pdf_utils import QUESTIONS, ScanError, render_page_png, split_scan

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Highest grade a single question can receive (4 questions x 5 = 20).
# ASSUMPTION: adjust if the exam uses another scale.
MAX_GRADE = 5.0

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-correction-service"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "correction.sqlite")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # scans can be large
db.init_app(app)

with app.app_context():
    db.create_all()


def parse_positive_int(raw, label):
    raw = (raw or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError("%s must be a positive integer" % label)
    return int(raw)


def assigned_professors():
    """{(exam_id, question_number): professor_id} for every assignment."""
    return {(a.exam_id, a.question_number): a.professor_id for a in ProfessorAssignment.query.all()}


@app.route("/")
def index():
    return redirect(url_for("list_assigned"))


# AD_4 - assign professors to the correction of a specific exam question
@app.route("/assignments", methods=["GET", "POST"])
def assignments():
    if request.method == "POST":
        try:
            exam_id = parse_positive_int(request.form.get("exam_id"), "exam identifier")
            professor_id = parse_positive_int(request.form.get("professor_id"), "professor identifier")
            question = parse_positive_int(request.form.get("question_number"), "question number")
            if question > QUESTIONS:
                raise ValueError("question number must be between 1 and %d" % QUESTIONS)
        except ValueError as e:
            flash(str(e), "error")
        else:
            existing = ProfessorAssignment.query.filter_by(exam_id=exam_id, question_number=question).first()
            if existing:
                # one professor per question: assigning again replaces the previous one
                existing.professor_id = professor_id
                flash("Question %d of exam %d reassigned to professor %d." % (question, exam_id, professor_id), "ok")
            else:
                db.session.add(
                    ProfessorAssignment(exam_id=exam_id, professor_id=professor_id, question_number=question)
                )
                flash("Question %d of exam %d assigned to professor %d." % (question, exam_id, professor_id), "ok")
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Could not save the assignment.", "error")
            return redirect(url_for("assignments"))
    rows = ProfessorAssignment.query.order_by(
        ProfessorAssignment.exam_id, ProfessorAssignment.question_number
    ).all()
    return render_template("assignments.html", assignments=rows, questions=range(1, QUESTIONS + 1))


# AD_5 - upload the scan of the exam resolutions
@app.route("/upload", methods=["GET", "POST"])
def upload_scan():
    if request.method == "POST":
        file = request.files.get("file")
        try:
            exam_id = parse_positive_int(request.form.get("exam_id"), "exam identifier")
            if not file or not file.filename:
                raise ValueError("choose a PDF file")
            data = file.read()
            pages = split_scan(data)
        except (ValueError, ScanError) as e:
            flash(str(e), "error")
        else:
            pdf = ExamCorrectionPdf(exam_id=exam_id, filename=file.filename, pdf_file=data)
            for sheet_number, question, page_pdf in pages:
                pdf.corrections.append(
                    QuestionCorrection(sheet_number=sheet_number, question_number=question, page_pdf=page_pdf)
                )
            db.session.add(pdf)
            db.session.commit()
            sheets = len(pages) // QUESTIONS
            flash(
                "Uploaded '%s' for exam %d: %d sheet(s), %d question page(s)."
                % (pdf.filename, exam_id, sheets, len(pages)),
                "ok",
            )
            return redirect(url_for("upload_scan"))
    uploads = []
    for pdf in ExamCorrectionPdf.query.order_by(ExamCorrectionPdf.id.desc()).all():
        uploads.append((pdf, len(pdf.corrections) // QUESTIONS))
    return render_template("upload.html", uploads=uploads)


# PR_1 - list the resolutions to correct (Part 1: all of them, whoever they are assigned to)
@app.route("/corrections")
def list_assigned():
    owners = assigned_professors()
    rows = []
    for c in (
        QuestionCorrection.query.join(ExamCorrectionPdf)
        .order_by(ExamCorrectionPdf.exam_id, QuestionCorrection.question_number, QuestionCorrection.id)
        .all()
    ):
        rows.append((c, owners.get((c.pdf.exam_id, c.question_number))))
    return render_template("corrections.html", rows=rows)


# PR_2 - correct an answer
@app.route("/corrections/<int:correction_id>", methods=["GET", "POST"])
def correct(correction_id):
    c = db.get_or_404(QuestionCorrection, correction_id)
    if request.method == "POST":
        raw = (request.form.get("grade") or "").strip().replace(",", ".")
        try:
            grade = float(raw)
            if not 0 <= grade <= MAX_GRADE:
                raise ValueError
        except ValueError:
            flash("Grade must be a number between 0 and %g." % MAX_GRADE, "error")
        else:
            c.grade = grade
            c.evaluated = True
            db.session.commit()
            flash("Grade %g saved for question %d of sheet %d." % (grade, c.question_number, c.sheet_number), "ok")
            return redirect(url_for("list_assigned"))
    owner = assigned_professors().get((c.pdf.exam_id, c.question_number))
    return render_template("correct.html", c=c, owner=owner, max_grade=MAX_GRADE)


# Page image for professors: QR code blacked out
@app.route("/corrections/<int:correction_id>/image.png")
def correction_image(correction_id):
    c = db.get_or_404(QuestionCorrection, correction_id)
    try:
        png = render_page_png(c.page_pdf, hide_qr=True)
    except ImportError:
        return "PyMuPDF is not installed (pip install pymupdf).", 500
    return send_file(io.BytesIO(png), mimetype="image/png")


# Original scanned page (QR code visible): only used by the student view (ST_3)
@app.route("/corrections/<int:correction_id>/scan.pdf")
def correction_scan(correction_id):
    c = db.get_or_404(QuestionCorrection, correction_id)
    return send_file(io.BytesIO(c.page_pdf), mimetype="application/pdf", download_name="page.pdf")


# PR_3 - list corrected answers
@app.route("/corrected")
def list_corrected():
    owners = assigned_professors()
    rows = []
    for c in (
        QuestionCorrection.query.join(ExamCorrectionPdf)
        .filter(QuestionCorrection.evaluated.is_(True))
        .order_by(ExamCorrectionPdf.exam_id, QuestionCorrection.sheet_number, QuestionCorrection.question_number)
        .all()
    ):
        rows.append((c, owners.get((c.pdf.exam_id, c.question_number))))
    return render_template("corrected.html", rows=rows)


# ST_3 (partial) - scans and corrections grouped by exam and sheet.
# The sheets carry no student identity here, so every sheet is listed.
@app.route("/scans")
def scans():
    exams = {}
    for c in (
        QuestionCorrection.query.join(ExamCorrectionPdf)
        .order_by(ExamCorrectionPdf.exam_id, ExamCorrectionPdf.id, QuestionCorrection.sheet_number,
                  QuestionCorrection.question_number)
        .all()
    ):
        sheet = exams.setdefault(c.pdf.exam_id, {}).setdefault((c.pdf.id, c.sheet_number), [])
        sheet.append(c)
    return render_template("scans.html", exams=exams)


if __name__ == "__main__":
    app.run(port=5004, debug=True)
