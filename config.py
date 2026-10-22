import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = (BASE_DIR / "marketplace.db").resolve()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))
    UNIVERSITY_EMAIL_DOMAIN = os.getenv("UNIVERSITY_EMAIL_DOMAIN", "klu.ac.in")
    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER", str(BASE_DIR / "app" / "static" / "uploads")
    )
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_TEST_MODE = os.getenv("RAZORPAY_TEST_MODE", "true").lower() == "true"
    RAZORPAY_CURRENCY = os.getenv("RAZORPAY_CURRENCY", "INR")
