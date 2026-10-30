from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ExamMixin:
    """An exam is given by its identifier, its course, or both."""

    exam_id = db.Column(db.Integer, nullable=True)
    course = db.Column(db.String(120), nullable=True)

    @property
    def exam_label(self):
        if self.exam_id is not None and self.course:
            return "%d (%s)" % (self.exam_id, self.course)
        return str(self.exam_id) if self.exam_id is not None else self.course

    def same_exam(self, other):
        """Equal identifiers when both have one, otherwise equal course names."""
        if self.exam_id is not None and other.exam_id is not None:
            return self.exam_id == other.exam_id
        if self.course and other.course:
            return self.course.lower() == other.course.lower()
        return False


class ProfessorAssignment(ExamMixin, db.Model):
    """Which professor corrects which question of an exam (AD_4)."""

    __tablename__ = "professor_assignment"

    id = db.Column(db.Integer, primary_key=True)
    # the professor is given by identifier, name, or both
    professor_id = db.Column(db.Integer, nullable=True)
    professor_name = db.Column(db.String(120), nullable=True)
    question_number = db.Column(db.Integer, nullable=False)

    @property
    def professor_label(self):
        if self.professor_id is not None and self.professor_name:
            return "%s (%d)" % (self.professor_name, self.professor_id)
        return self.professor_name or str(self.professor_id)


class ExamCorrectionPdf(ExamMixin, db.Model):
    """An uploaded scan (many resolution sheets in one PDF) (AD_5), stored as received."""

    __tablename__ = "exam_correction_pdfs"

    id = db.Column(db.Integer, primary_key=True)
    # <timestamp>_user-<id of the uploader>_<original name>.pdf
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    # False while the administrator has still to confirm that sheets uploaded
    # before are replaced; the pages of the PDF are only created once confirmed.
    confirmed = db.Column(db.Boolean, nullable=False, default=False)
    # deferred: not loaded unless accessed, so listings stay light
    pdf_file = db.deferred(db.Column(db.LargeBinary, nullable=False))

    corrections = db.relationship(
        "QuestionCorrection", backref="pdf", cascade="all, delete-orphan", lazy=True
    )


class QuestionCorrection(ExamMixin, db.Model):
    """One scanned question page and its correction."""

    __tablename__ = "question_corrections"
    __table_args__ = (
        # a sheet has a single answer page per question
        db.UniqueConstraint("sheet_id", "question_number", name="uq_sheet_question"),
    )

    id = db.Column(db.Integer, primary_key=True)
    pdf_id = db.Column(db.Integer, db.ForeignKey("exam_correction_pdfs.id"), nullable=False)
    # identifier read from the QR code of the sheet
    sheet_id = db.Column(db.Integer, nullable=False)
    question_number = db.Column(db.Integer, nullable=False)
    # image of the page, with the QR codes already covered
    page_png = db.deferred(db.Column(db.LargeBinary, nullable=False))
    evaluated = db.Column(db.Boolean, nullable=False, default=False)
    grade = db.Column(db.Float, nullable=True)
