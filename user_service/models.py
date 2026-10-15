from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

ROLES = ["administrator", "professor", "student", "exam invigilator"]


class User(db.Model):
    __tablename__ = "users"

    # Part 1: simple integer identifier. It may be supplied (e.g. a student
    # number) or auto-assigned by the database when left empty.
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(32), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        # never expose the password
        return {"id": self.id, "name": self.name, "role": self.role}
