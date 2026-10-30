from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class PrintJob(db.Model):
    """The printed resolution sheets of one exam (one PDF with all the sheets)."""

    __tablename__ = "print_jobs"

    # same identifier as in the Admin Service
    exam_id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    course = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    # exam-<id>_<timestamp>_user-<id of the user that ordered the printing>.pdf
    filename = db.Column(db.String(255), nullable=False)
    pdf_file = db.deferred(db.Column(db.LargeBinary, nullable=False))

    sheets = db.relationship(
        "ResolutionSheet", backref="job", cascade="all, delete-orphan", lazy=True
    )


class ResolutionSheet(db.Model):
    """One anonymous resolution sheet. Its id is the value encoded in the QR code."""

    __tablename__ = "resolution_sheets"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("print_jobs.exam_id"), nullable=False)
    # position of the sheet inside the printed PDF (1-based)
    sheet_number = db.Column(db.Integer, nullable=False)
    # Filled in when an invigilator scans the QR code and assigns the sheet to a student.
    student_id = db.Column(db.Integer, nullable=True)
    invigilator_id = db.Column(db.Integer, nullable=True)
