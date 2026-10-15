from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Exam(db.Model):
    __tablename__ = "exams"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    course = db.Column(db.String(120), nullable=False)
    # Set once the Printing Service accepted the order (AD_3), so the same
    # exam is not printed twice by accident.
    printing_ordered = db.Column(db.Boolean, nullable=False, default=False)

    enrollments = db.relationship(
        "Enrollment", backref="exam", cascade="all, delete-orphan", lazy=True
    )

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "course": self.course,
            "printing_ordered": self.printing_ordered,
            "enrolled": len(self.enrollments),
        }


class Enrollment(db.Model):
    __tablename__ = "enrolled_students"

    # composite primary key: a student can be enrolled only once per exam
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), primary_key=True)
    student_id = db.Column(db.Integer, primary_key=True, autoincrement=False)
