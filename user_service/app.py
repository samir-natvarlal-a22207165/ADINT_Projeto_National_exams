import csv
import io
import os

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from models import ROLES, User, db

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-user-service"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "users.sqlite")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()


def normalize_role(raw):
    role = (raw or "").strip().lower()
    return role if role in ROLES else None


def parse_identifier(raw):
    """Empty -> None (auto id). Otherwise must be a positive integer."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError("identifier must be a positive integer")
    return int(raw)


def build_user(name, identifier, password, role):
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    if not password:
        raise ValueError("password is required")
    role = normalize_role(role)
    if role is None:
        raise ValueError("role must be one of: " + ", ".join(ROLES))
    user = User(id_extra=parse_identifier(identifier), name=name, role=role)
    user.set_password(password)
    return user


@app.route("/")
def index():
    return redirect(url_for("list_users"))


# SU_1 - list users
@app.route("/users")
def list_users():
    role = request.args.get("role")
    query = User.query.order_by(User.id)
    if role in ROLES:
        query = query.filter_by(role=role)
    return render_template("users.html", users=query.all(), roles=ROLES, selected=role)


# SU_2 - add user
@app.route("/users/add", methods=["GET", "POST"])
def add_user():
    if request.method == "POST":
        try:
            user = build_user(
                request.form.get("name"),
                request.form.get("identifier"),
                request.form.get("password"),
                request.form.get("role"),
            )
            db.session.add(user)
            db.session.commit()
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
        except IntegrityError:
            db.session.rollback()
            flash("A user with that identifier already exists.", "error")
        else:
            flash("User %d (%s) added." % (user.id, user.name), "ok")
            return redirect(url_for("list_users"))
    return render_template("add_user.html", roles=ROLES)


# SU_3 - bulk add users from a CSV file: name,identifier,password,role
@app.route("/users/bulk", methods=["GET", "POST"])
def bulk_add_users():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Choose a CSV file.", "error")
            return render_template("bulk_add.html", roles=ROLES)

        try:
            text = file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("File must be UTF-8 encoded.", "error")
            return render_template("bulk_add.html", roles=ROLES)

        reader = csv.DictReader(io.StringIO(text))
        reader.fieldnames = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
        missing = {"name", "password", "role"} - set(reader.fieldnames)
        if missing:
            flash("Missing CSV column(s): " + ", ".join(sorted(missing)), "error")
            return render_template("bulk_add.html", roles=ROLES)

        added, errors = 0, []
        for line_no, row in enumerate(reader, start=2):
            try:
                user = build_user(
                    row.get("name"), row.get("identifier"), row.get("password"), row.get("role")
                )
                # savepoint so one bad row does not undo the good ones
                with db.session.begin_nested():
                    db.session.add(user)
                added += 1
            except ValueError as e:
                errors.append("line %d: %s" % (line_no, e))
            except IntegrityError:
                errors.append("line %d: identifier already exists" % line_no)
        db.session.commit()

        return render_template("bulk_add.html", roles=ROLES, added=added, errors=errors)
    return render_template("bulk_add.html", roles=ROLES)


# JSON endpoints for the other services (Admin, Proxy, ...) to use later
@app.route("/api/users")
def api_users():
    role = request.args.get("role")
    query = User.query.order_by(User.id)
    if role in ROLES:
        query = query.filter_by(role=role)
    return jsonify([u.to_dict() for u in query.all()])


@app.route("/api/users/<int:user_id>")
def api_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(user.to_dict())

@app.route("/api/users/by-id-extra/<int:id_extra>")
def api_user_by_id_extra(id_extra):
    user = User.query.filter_by(id_extra=id_extra).first()
    if user is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(user.to_dict())

if __name__ == "__main__":
    app.run(port=5001, debug=True)
