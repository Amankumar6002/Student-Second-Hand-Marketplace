from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_

from ..extensions import db
from ..models import User

auth_bp = Blueprint("auth", __name__)


def active_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_active:
            logout_user()
            flash("Your account has been suspended.", "danger")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("products.home"))
    if request.method == "POST":
        email = request.form.get("university_email", "").strip().lower()
        password = request.form.get("password", "")
        if not email.endswith("@" + current_app.config["UNIVERSITY_EMAIL_DOMAIN"]):
            flash("Use your Kalasalingam University email address.", "danger")
        elif password != request.form.get("confirm_password") or len(password) < 8:
            flash("Passwords must match and contain at least 8 characters.", "danger")
        elif User.query.filter(or_(User.university_email == email, User.registration_number == request.form.get("registration_number", "").strip())).first():
            flash("An account with those details already exists.", "danger")
        else:
            user = User(
                name=request.form.get("name", "").strip(),
                registration_number=request.form.get("registration_number", "").strip(),
                university_email=email,
                department=request.form.get("department", "").strip(),
                section=request.form.get("section", "").strip(),
                phone=request.form.get("phone", "").strip(),
                profile_image=None,
                role="student",
                is_verified=False,
                is_active=True,
            )
            user.set_password(password)
            try:
                db.session.add(user)
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                flash(f"Registration failed while saving your account: {exc}", "danger")
                return render_template("auth/register.html")
            flash("Account created. An administrator will verify your student status.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(university_email=request.form.get("email", "").strip().lower()).first()
        if user and user.check_password(request.form.get("password", "")) and user.is_active:
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(request.args.get("next") or (url_for("admin.dashboard") if user.role == "admin" else url_for("products.home")))
        flash("Invalid credentials or inactive account.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("products.home"))
