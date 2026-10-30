import io
import math
import os
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from models import ExamCorrectionPdf, ProfessorAssignment, QuestionCorrection, db
from pdf_utils import QUESTIONS, InvalidPdfError, ScanError, split_scan
from utils import MAX_ID, BoundedIntConverter, parse_positive_int

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# The uploader of a scan is not known (there is no login).
UPLOADER_PLACEHOLDER = "unknown"


app = Flask(__name__)
app.url_map.converters["int"] = BoundedIntConverter
app.config["SECRET_KEY"] = "dev-correction-service"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "correction.sqlite")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # scans can be large
db.init_app(app)

with app.app_context():
    db.create_all()


@app.errorhandler(413)
def file_too_large(error):
    flash("The file is too large (limit: %d MB)." % (app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)), "error")
    return redirect(url_for("upload_scan"))


def parse_exam(form):
    """(exam_id, course) from a form; at least one of the two is required."""
    exam_id = parse_positive_int(form.get("exam_id"), "exam identifier", required=False)
    course = (form.get("course") or "").strip() or None
    if exam_id is None and course is None:
        raise ValueError("give the exam identifier, the course, or both")
    return exam_id, course


def assigned_professor(answer, assignments):
    """Label of the professor assigned to the question of an answer, or None."""
    for a in assignments:
        if a.question_number == answer.question_number and a.same_exam(answer):
            return a.professor_label
    return None


def scanned_exams():
    """(exam identifiers, courses) given in the saved uploads, for the dropdowns of AD_4."""
    pdfs = ExamCorrectionPdf.query.filter(ExamCorrectionPdf.confirmed.is_(True))
    exam_ids = pdfs.filter(ExamCorrectionPdf.exam_id.isnot(None)).with_entities(ExamCorrectionPdf.exam_id).distinct()
    courses = pdfs.filter(ExamCorrectionPdf.course.isnot(None)).with_entities(ExamCorrectionPdf.course).distinct()
    return sorted(e for (e,) in exam_ids), sorted((c for (c,) in courses), key=str.lower)


@app.route("/")
def index():
    return redirect(url_for("list_assigned"))


# AD_4 - assign professors to the correction of a specific exam question
@app.route("/assignments", methods=["GET", "POST"])
def assignments():
    exam_ids, courses = scanned_exams()
    if request.method == "POST":
        try:
            exam_id, course = parse_exam(request.form)
            # the dropdowns only offer the exams of the uploaded scans
            if exam_id is not None and exam_id not in exam_ids:
                raise ValueError("exam %d is not in any uploaded scan" % exam_id)
            if course is not None and course not in courses:
                raise ValueError("course '%s' is not in any uploaded scan" % course)
            question = parse_positive_int(request.form.get("question_number"), "question number")
            if question > QUESTIONS:
                raise ValueError("question number must be between 1 and %d" % QUESTIONS)
            professor_id = parse_positive_int(request.form.get("professor_id"), "professor identifier", required=False)
            professor_name = (request.form.get("professor_name") or "").strip() or None
            if professor_id is None and professor_name is None:
                raise ValueError("give the professor identifier, the name, or both")
        except ValueError as e:
            flash(str(e), "error")
        else:
            # one professor per question: assigning again replaces the previous one
            assignment = ProfessorAssignment.query.filter(
                ProfessorAssignment.exam_id == exam_id,
                ProfessorAssignment.course == course,
                ProfessorAssignment.question_number == question,
            ).first()
            if assignment is None:
                assignment = ProfessorAssignment(exam_id=exam_id, course=course, question_number=question)
                db.session.add(assignment)
            assignment.professor_id = professor_id
            assignment.professor_name = professor_name
            db.session.commit()
            flash(
                "Question %d of exam %s assigned to %s."
                % (question, assignment.exam_label, assignment.professor_label),
                "ok",
            )
            return redirect(url_for("assignments"))
    rows = ProfessorAssignment.query.order_by(
        ProfessorAssignment.exam_id, ProfessorAssignment.course, ProfessorAssignment.question_number
    ).all()
    return render_template(
        "assignments.html", assignments=rows, questions=range(1, QUESTIONS + 1),
        exam_ids=exam_ids, courses=courses,
    )


def read_upload(data):
    """Split a scan into sheets.

    Returns (sheets, warnings): sheets is a list of
    (sheet_id, [png_question_1 .. png_question_4]) and warnings lists the sheets
    that were skipped. Raises ScanError if the PDF is unusable.
    """
    warnings, sheets, seen = [], [], {}
    for position, value, pngs in split_scan(data):
        if not (value.isdecimal() and 0 < int(value) <= MAX_ID):
            warnings.append(
                "Sheet %d of the PDF was skipped: its QR code ('%s') is not a sheet identifier."
                % (position, value[:40])
            )
        elif int(value) in seen:
            warnings.append(
                "Sheet %d of the PDF was skipped: sheet %s already appears as sheet %d of the same PDF."
                % (position, value, seen[int(value)])
            )
        else:
            seen[int(value)] = position
            sheets.append((int(value), pngs))
    return sheets, warnings


def find_conflicts(sheets):
    """Sheets of an upload that were already uploaded before.

    Returns [(sheet_id, previous_pdf, graded_answers)] ordered by sheet.
    """
    sheet_ids = [sheet_id for sheet_id, _ in sheets]
    previous = {}
    for c in QuestionCorrection.query.filter(QuestionCorrection.sheet_id.in_(sheet_ids)).order_by(
        QuestionCorrection.sheet_id, QuestionCorrection.question_number
    ):
        entry = previous.setdefault(c.sheet_id, [c.pdf, 0])
        entry[1] += 1 if c.evaluated else 0
    return [(sheet_id, pdf, graded) for sheet_id, (pdf, graded) in sorted(previous.items())]


def save_sheets(pdf, sheets):
    """Create the question pages of an upload, replacing the ones of the same sheets."""
    sheet_ids = [sheet_id for sheet_id, _ in sheets]
    QuestionCorrection.query.filter(QuestionCorrection.sheet_id.in_(sheet_ids)).delete(
        synchronize_session=False
    )
    for sheet_id, pngs in sheets:
        for question, png in enumerate(pngs, start=1):
            pdf.corrections.append(
                QuestionCorrection(
                    exam_id=pdf.exam_id, course=pdf.course, sheet_id=sheet_id,
                    question_number=question, page_png=png,
                )
            )
    pdf.confirmed = True
    db.session.commit()


def stored_name(original):
    name = secure_filename(original or "") or "scan.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return "%s_user-%s_%s" % (datetime.now().strftime("%Y%m%d-%H%M%S"), UPLOADER_PLACEHOLDER, name)


# AD_5 - upload the scan of the exam resolutions
@app.route("/upload", methods=["GET", "POST"])
def upload_scan():
    if request.method == "POST":
        file = request.files.get("file")
        try:
            if not file or not file.filename:
                raise InvalidPdfError("Choose a PDF file.")
            exam_id, course = parse_exam(request.form)
            data = file.read()
            if not data:
                raise InvalidPdfError("The file is empty.")
            sheets, warnings = read_upload(data)
        except ValueError as e:
            flash(str(e), "error")
        else:
            for warning in warnings:
                flash(warning, "warning")
            if not sheets:
                flash("No sheet of the PDF could be used, nothing was saved.", "error")
            else:
                pdf = ExamCorrectionPdf(
                    exam_id=exam_id, course=course, filename=stored_name(file.filename), pdf_file=data
                )
                db.session.add(pdf)
                conflicts = find_conflicts(sheets)
                try:
                    if conflicts:
                        # kept (as received) until the administrator confirms the replacement
                        db.session.commit()
                        return redirect(url_for("confirm_upload", pdf_id=pdf.id))
                    save_sheets(pdf, sheets)
                except IntegrityError:
                    db.session.rollback()
                    flash("The sheets could not be saved, try again.", "error")
                else:
                    flash(
                        "Uploaded '%s' for exam %s: %d sheet(s), %d question page(s)."
                        % (pdf.filename, pdf.exam_label, len(sheets), len(sheets) * QUESTIONS),
                        "ok",
                    )
                    return redirect(url_for("upload_scan"))
    uploads = []
    for pdf in ExamCorrectionPdf.query.order_by(ExamCorrectionPdf.id.desc()).all():
        pages = QuestionCorrection.query.filter(QuestionCorrection.pdf_id == pdf.id).count()
        uploads.append((pdf, pages // QUESTIONS))
    return render_template("upload.html", uploads=uploads)


# Sheets that were already uploaded: ask before replacing them (and their grades)
@app.route("/uploads/<int:pdf_id>/confirm", methods=["GET", "POST"])
def confirm_upload(pdf_id):
    pdf = ExamCorrectionPdf.query.filter(ExamCorrectionPdf.id == pdf_id).first_or_404()
    if pdf.confirmed:
        flash("That upload was already confirmed.", "error")
        return redirect(url_for("upload_scan"))
    try:
        sheets, _ = read_upload(pdf.pdf_file)
    except ScanError as e:
        flash(str(e), "error")
        return redirect(url_for("upload_scan"))
    if request.method == "POST":
        try:
            save_sheets(pdf, sheets)
        except IntegrityError:
            db.session.rollback()
            flash("The sheets could not be saved, try again.", "error")
            return redirect(url_for("upload_scan"))
        flash("Sheets of '%s' replaced the previous ones." % pdf.filename, "ok")
        return redirect(url_for("upload_scan"))
    return render_template("confirm_overwrite.html", pdf=pdf, conflicts=find_conflicts(sheets))


@app.route("/uploads/<int:pdf_id>/cancel", methods=["POST"])
def cancel_upload(pdf_id):
    pdf = ExamCorrectionPdf.query.filter(ExamCorrectionPdf.id == pdf_id).first_or_404()
    if not pdf.confirmed:
        db.session.delete(pdf)
        db.session.commit()
        flash("Upload cancelled, nothing was replaced.", "ok")
    return redirect(url_for("upload_scan"))


# The original PDF, exactly as it was uploaded
@app.route("/uploads/<int:pdf_id>/original.pdf")
def upload_original(pdf_id):
    pdf = ExamCorrectionPdf.query.filter(ExamCorrectionPdf.id == pdf_id).first_or_404()
    return send_file(io.BytesIO(pdf.pdf_file), mimetype="application/pdf", download_name=pdf.filename)


# PR_1 - list the resolutions to correct, whoever they are assigned to
@app.route("/corrections")
def list_assigned():
    owners = ProfessorAssignment.query.all()
    rows = []
    for c in QuestionCorrection.query.order_by(
        QuestionCorrection.exam_id, QuestionCorrection.course, QuestionCorrection.question_number, QuestionCorrection.id
    ).all():
        rows.append((c, assigned_professor(c, owners)))
    return render_template("corrections.html", rows=rows)


# PR_2 - correct an answer
@app.route("/corrections/<int:correction_id>", methods=["GET", "POST"])
def correct(correction_id):
    c = QuestionCorrection.query.filter(QuestionCorrection.id == correction_id).first_or_404()
    if request.method == "POST":
        raw = (request.form.get("grade") or "").strip().replace(",", ".")
        try:
            grade = float(raw)
            if not (math.isfinite(grade) and grade >= 0):
                raise ValueError
        except ValueError:
            flash("Grade must be a number of at least 0.", "error")
        else:
            c.grade = grade
            c.evaluated = True
            db.session.commit()
            flash("Grade %g saved for answer %d (question %d)." % (grade, c.id, c.question_number), "ok")
            return redirect(url_for("list_assigned"))
    owner = assigned_professor(c, ProfessorAssignment.query.all())
    return render_template("correct.html", c=c, owner=owner)


# Page image: the QR codes were already covered when the scan was uploaded
@app.route("/corrections/<int:correction_id>/image.png")
def correction_image(correction_id):
    c = QuestionCorrection.query.filter(QuestionCorrection.id == correction_id).first_or_404()
    return send_file(io.BytesIO(c.page_png), mimetype="image/png")


# PR_3 - list corrected answers
@app.route("/corrected")
def list_corrected():
    owners = ProfessorAssignment.query.all()
    rows = []
    for c in (
        QuestionCorrection.query.filter(QuestionCorrection.evaluated.is_(True))
        .order_by(
            QuestionCorrection.exam_id, QuestionCorrection.course, QuestionCorrection.question_number, QuestionCorrection.id
        )
        .all()
    ):
        rows.append((c, assigned_professor(c, owners)))
    return render_template("corrected.html", rows=rows)


# ST_3 - scans and corrections grouped by exam and sheet.
# The sheets carry no student identity, so every sheet is listed.
@app.route("/scans")
def scans():
    exams = {}
    for c in QuestionCorrection.query.order_by(
        QuestionCorrection.exam_id, QuestionCorrection.course, QuestionCorrection.sheet_id, QuestionCorrection.question_number
    ).all():
        exams.setdefault(c.exam_label, {}).setdefault(c.sheet_id, []).append(c)
    return render_template("scans.html", exams=exams)


if __name__ == "__main__":
    app.run(port=5004, debug=True)
