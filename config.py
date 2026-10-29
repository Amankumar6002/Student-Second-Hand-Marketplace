import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = (BASE_DIR / "marketplace.db").resolve()

load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))
    UNIVERSITY_EMAIL_DOMAIN = os.getenv("UNIVERSITY_EMAIL_DOMAIN", "klu.ac.in")
    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER", str(BASE_DIR / "app" / "static" / "uploads")
    )
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:5000"
    SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL") or os.getenv("MAIL_USERNAME")

    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "465"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "False").lower() == "true"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "True").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
    # Admin notifications prefer a dedicated address, then support, then mail.
    ADMIN_NOTIFICATION_EMAIL = (
        os.getenv("ADMIN_NOTIFICATION_EMAIL") or SUPPORT_EMAIL or MAIL_USERNAME
    )
    RESEND_API_KEY = os.getenv("RESEND_API_KEY")
    RESEND_FROM = os.getenv("RESEND_FROM")
    RESEND_TEST_MODE = (
        os.getenv("RESEND_TEST_MODE", "false").strip().lower() == "true"
    )
    RESEND_TEST_RECIPIENT = (
        os.getenv("RESEND_TEST_RECIPIENT") or "delivered@resend.dev"
    )
