from functools import wraps
import secrets
from urllib.parse import urlsplit
from uuid import uuid4

from authlib.integrations.base_client.errors import OAuthError
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from requests.exceptions import RequestException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import User

auth_bp = Blueprint("auth", __name__)


def _safe_next_url(target):
    if not target or "\\" in target:
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


def _google_login_error(message):
    flash(message, "danger")
    return redirect(url_for("auth.login"))


def _google_client():
    oauth = current_app.extensions["authlib.integrations.flask_client"]
    return oauth.create_client("google")


def _google_configuration_error():
    missing_settings = [
        setting
        for setting in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
        if not current_app.config.get(setting)
    ]
    if not missing_settings:
        return "Google sign-in is temporarily unavailable. Please try again."
    return (
        "Google sign-in is not configured. Set "
        + " and ".join(missing_settings)
        + " in the project-root .env file or environment, then restart the app."
    )


def _finish_google_login(user):
    if not user.is_active:
        session.pop("google_login_next", None)
        return _google_login_error(
            "Your account has been suspended. You can contact support using the link below."
        )
    login_user(user)
    destination = _safe_next_url(session.pop("google_login_next", None))
    return redirect(destination or (
        url_for("admin.dashboard") if user.role == "admin" else url_for("products.home")
    ))


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
            except IntegrityError:
                db.session.rollback()
                flash("An account with those details already exists.", "danger")
                return render_template("auth/register.html")
            flash("Account created. An administrator will verify your student status.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(university_email=request.form.get("email", "").strip().lower()).first()
        if user and user.check_password(request.form.get("password", "")):
            if not user.is_active:
                flash(
                    "Your account has been suspended. You can contact support using the link below.",
                    "danger",
                )
            else:
                login_user(user, remember=bool(request.form.get("remember")))
                destination = _safe_next_url(request.args.get("next"))
                return redirect(destination or (url_for("admin.dashboard") if user.role == "admin" else url_for("products.home")))
        else:
            flash("Invalid credentials.", "danger")
    return render_template(
        "auth/login.html",
        support_email=current_app.config.get("SUPPORT_EMAIL"),
    )


@auth_bp.route("/login/google")
def google_login():
    next_url = request.args.get("next")
    if next_url and _safe_next_url(next_url) is None:
        session.pop("google_login_next", None)
        return _google_login_error("The requested sign-in destination is invalid.")
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get("GOOGLE_CLIENT_SECRET"):
        session.pop("google_login_next", None)
        return _google_login_error(_google_configuration_error())

    google = _google_client()
    if google is None:
        session.pop("google_login_next", None)
        return _google_login_error("Google sign-in is temporarily unavailable. Please try again.")
    session["google_login_next"] = _safe_next_url(next_url)
    try:
        return google.authorize_redirect(url_for("auth.google_callback", _external=True))
    except (OAuthError, RequestException, OSError, TimeoutError):
        current_app.logger.warning("Google sign-in could not be started")
        session.pop("google_login_next", None)
        return _google_login_error("Google sign-in is temporarily unavailable. Please try again.")


@auth_bp.route("/login/google/callback")
def google_callback():
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get("GOOGLE_CLIENT_SECRET"):
        session.pop("google_login_next", None)
        return _google_login_error(_google_configuration_error())

    if request.args.get("error"):
        session.pop("google_login_next", None)
        return _google_login_error("Google sign-in was cancelled or could not be completed.")

    google = _google_client()
    if google is None:
        session.pop("google_login_next", None)
        return _google_login_error(_google_configuration_error())
    try:
        token = google.authorize_access_token()
    except (OAuthError, RequestException, OSError, TimeoutError, ValueError):
        current_app.logger.warning("Google sign-in response could not be validated")
        session.pop("google_login_next", None)
        return _google_login_error("Google sign-in could not be verified. Please try again.")

    profile = token.get("userinfo") if isinstance(token, dict) else None
    if not isinstance(profile, dict):
        session.pop("google_login_next", None)
        return _google_login_error("Google did not provide a valid account profile.")

    subject = profile.get("sub")
    email = profile.get("email")
    name = profile.get("name")
    if (
        not isinstance(subject, str)
        or not subject.strip()
        or len(subject.strip()) > 255
        or not isinstance(email, str)
        or len(email.strip()) > 160
        or not isinstance(name, str)
        or not name.strip()
        or len(name.strip()) > 120
        or profile.get("email_verified") is not True
    ):
        session.pop("google_login_next", None)
        return _google_login_error("Google did not provide the verified account details required to sign in.")

    email = email.strip().lower()
    if email.count("@") != 1 or any(character.isspace() for character in email):
        session.pop("google_login_next", None)
        return _google_login_error("Google did not provide a valid university email address.")
    email_local_part, email_domain = email.rsplit("@", 1)
    university_domain = current_app.config["UNIVERSITY_EMAIL_DOMAIN"].strip().lower()
    if not email_local_part or not email_domain or email_domain != university_domain:
        session.pop("google_login_next", None)
        return _google_login_error("Use your verified university email address to sign in.")

    subject = subject.strip()
    picture = profile.get("picture")
    picture_parts = urlsplit(picture) if isinstance(picture, str) else None
    picture = (
        picture
        if picture_parts
        and picture_parts.scheme == "https"
        and picture_parts.netloc
        and len(picture) <= 500
        else None
    )

    user = User.query.filter_by(google_subject=subject).first()
    if user is None:
        user = User.query.filter_by(university_email=email).first()
        if user is not None and user.google_subject not in (None, subject):
            session.pop("google_login_next", None)
            return _google_login_error("This email is already linked to another Google account.")

    try:
        if user is None:
            user = User(
                name=name.strip(),
                registration_number=f"GOOGLE-{uuid4().hex}",
                university_email=email,
                department="Not provided",
                section="Not provided",
                role="student",
                is_verified=False,
                is_active=True,
                google_subject=subject,
                google_picture_url=picture,
            )
            user.set_password(secrets.token_urlsafe(32))
            db.session.add(user)
        else:
            user.google_subject = subject
            user.google_picture_url = picture
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        user = User.query.filter_by(google_subject=subject).first()
        if user is None:
            user = User.query.filter_by(university_email=email).first()
            if user is not None and user.google_subject is None:
                user.google_subject = subject
                user.google_picture_url = picture
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    user = User.query.filter_by(google_subject=subject).first()
            else:
                user = None
        if user is None:
            current_app.logger.warning("Google account could not be saved because of an integrity conflict")
            session.pop("google_login_next", None)
            return _google_login_error("We could not create or link your account. Please try again.")
    return _finish_google_login(user)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("products.home"))
