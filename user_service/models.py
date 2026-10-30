from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

ROLES = ["administrator", "professor", "student", "exam invigilator"]


class User(db.Model):
    __tablename__ = "users"

    # Identifier used by every service. It may be supplied when the user is
    # added, otherwise the database assigns the next free one.
    id = db.Column(db.Integer, primary_key=True)
    student_number = db.Column(db.Integer, unique=True, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(32), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        # never expose the password
        return {"id": self.id, "student_number": self.student_number, "name": self.name, "role": self.role}
