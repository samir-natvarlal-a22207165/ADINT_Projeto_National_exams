from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ProfessorAssignment(db.Model):
    """Which professor corrects which question of an exam (AD_4)."""

    __tablename__ = "professor_assignment"
    __table_args__ = (
        # each question is corrected by a single professor
        db.UniqueConstraint("exam_id", "question_number", name="uq_exam_question"),
    )

    id = db.Column(db.Integer, primary_key=True)
    professor_id = db.Column(db.Integer, nullable=False)
    exam_id = db.Column(db.Integer, nullable=False)
    question_number = db.Column(db.Integer, nullable=False)


class ExamCorrectionPdf(db.Model):
    """An uploaded scan (many resolution sheets in one PDF) (AD_5)."""

    __tablename__ = "exam_correction_pdfs"

    id = db.Column(db.Integer, primary_key=True)
    # Part 1: just a number typed by the administrator, not checked against the Admin Service.
    exam_id = db.Column(db.Integer, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    # deferred: not loaded unless accessed, so listings stay light
    pdf_file = db.deferred(db.Column(db.LargeBinary, nullable=False))

    corrections = db.relationship(
        "QuestionCorrection", backref="pdf", cascade="all, delete-orphan", lazy=True
    )


class QuestionCorrection(db.Model):
    """One scanned question page and its correction."""

    __tablename__ = "question_corrections"

    id = db.Column(db.Integer, primary_key=True)
    pdf_id = db.Column(db.Integer, db.ForeignKey("exam_correction_pdfs.id"), nullable=False)
    # position of the sheet inside the uploaded scan (1-based)
    sheet_number = db.Column(db.Integer, nullable=False)
    # identifier read from the QR code of the sheet (Printing Service)
    sheet_id = db.Column(db.Integer, nullable=False)
    question_number = db.Column(db.Integer, nullable=False)
    page_pdf = db.deferred(db.Column(db.LargeBinary, nullable=False))
    evaluated = db.Column(db.Boolean, nullable=False, default=False)
    grade = db.Column(db.Float, nullable=True)
