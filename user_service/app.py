import os

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from models import ROLES, User, db
from utils import BoundedIntConverter, parse_positive_int, read_csv_upload

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.url_map.converters["int"] = BoundedIntConverter
app.config["SECRET_KEY"] = "dev-user-service"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "users.sqlite")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()


def normalize_role(raw):
    role = (raw or "").strip().lower()
    return role if role in ROLES else None


def next_student_number():
    return (db.session.query(func.max(User.student_number)).scalar() or 0) + 1


def build_user(fields):
    """User from a form or a CSV row, plus warnings about identifiers that were replaced.

    id and student_number are optional; one that is already taken is replaced
    by a new one (the database picks the id, the student number is the next free one).
    """
    name = (fields.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    password = fields.get("password")
    if not password:
        raise ValueError("password is required")
    role = normalize_role(fields.get("role"))
    if role is None:
        raise ValueError("role must be one of: " + ", ".join(ROLES))
    user_id = parse_positive_int(fields.get("id"), "id", required=False)
    number = parse_positive_int(fields.get("student_number"), "student number", required=False)

    warnings = []
    if user_id is not None and db.session.get(User, user_id) is not None:
        warnings.append("id %d already exists, a new one was assigned" % user_id)
        user_id = None
    if number is not None and User.query.filter(User.student_number == number).first() is not None:
        new_number = next_student_number()
        warnings.append("student number %d already exists, %d was assigned" % (number, new_number))
        number = new_number

    user = User(id=user_id, student_number=number, name=name, role=role)
    user.set_password(password)
    return user, warnings


@app.route("/")
def index():
    return redirect(url_for("list_users"))


# SU_1 - list users
@app.route("/users")
def list_users():
    role = request.args.get("role")
    query = User.query.order_by(User.id)
    if role in ROLES:
        query = query.filter(User.role == role)
    return render_template("users.html", users=query.all(), roles=ROLES, selected=role)


# SU_2 - add user
@app.route("/users/add", methods=["GET", "POST"])
def add_user():
    if request.method == "POST":
        try:
            user, warnings = build_user(request.form)
            db.session.add(user)
            db.session.commit()
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
        except IntegrityError:
            db.session.rollback()
            flash("A user with that identifier already exists.", "error")
        else:
            for warning in warnings:
                flash(warning, "warning")
            flash("User %d (%s) added." % (user.id, user.name), "ok")
            return redirect(url_for("list_users"))
    return render_template("add_user.html", roles=ROLES)


# SU_3 - bulk add users from a CSV file: name,password,role and optionally id,student_number
@app.route("/users/bulk", methods=["GET", "POST"])
def bulk_add_users():
    if request.method == "POST":
        try:
            reader = read_csv_upload(request.files.get("file"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("bulk_add.html", roles=ROLES)
        missing = {"name", "password", "role"} - set(reader.fieldnames)
        if missing:
            flash("Missing CSV column(s): " + ", ".join(sorted(missing)), "error")
            return render_template("bulk_add.html", roles=ROLES)

        added, errors, warnings = 0, [], []
        for line_no, row in enumerate(reader, start=2):
            try:
                user, row_warnings = build_user(row)
                # savepoint so one bad row does not undo the good ones
                with db.session.begin_nested():
                    db.session.add(user)
                added += 1
                warnings.extend("line %d: %s" % (line_no, w) for w in row_warnings)
            except ValueError as e:
                errors.append("line %d: %s" % (line_no, e))
            except IntegrityError:
                errors.append("line %d: identifier already exists" % line_no)
        db.session.commit()

        return render_template("bulk_add.html", roles=ROLES, added=added, errors=errors, warnings=warnings)
    return render_template("bulk_add.html", roles=ROLES)


# JSON endpoints for other services
@app.route("/api/users")
def api_users():
    role = request.args.get("role")
    query = User.query.order_by(User.id)
    if role in ROLES:
        query = query.filter(User.role == role)
    return jsonify([u.to_dict() for u in query.all()])


@app.route("/api/users/<int:user_id>")
def api_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(user.to_dict())


@app.route("/api/users/by-student-number/<int:number>")
def api_user_by_student_number(number):
    user = User.query.filter(User.student_number == number).first()
    if user is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(user.to_dict())


if __name__ == "__main__":
    app.run(port=5001, debug=True)
