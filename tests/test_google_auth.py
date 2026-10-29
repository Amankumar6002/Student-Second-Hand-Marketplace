import unittest
from unittest.mock import Mock, patch

from flask import redirect
from sqlalchemy import text

from app import create_app, ensure_database_schema
from app.extensions import db
from app.models import User
from config import Config


class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    TESTING = True
    WTF_CSRF_ENABLED = False
    GOOGLE_CLIENT_ID = "test-google-client-id"
    GOOGLE_CLIENT_SECRET = "test-google-client-secret"
    RESEND_API_KEY = None
    RESEND_FROM = None


class FakeGoogleClient:
    def __init__(self, profile=None, error=None):
        self.profile = profile
        self.error = error

    def authorize_redirect(self, redirect_uri):
        return redirect("https://accounts.google.com/o/oauth2/v2/auth")

    def authorize_access_token(self):
        if self.error:
            raise self.error
        return {"userinfo": self.profile}


class GoogleAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestConfig)

    def setUp(self):
        self.app.config["GOOGLE_CLIENT_ID"] = TestConfig.GOOGLE_CLIENT_ID
        self.app.config["GOOGLE_CLIENT_SECRET"] = TestConfig.GOOGLE_CLIENT_SECRET
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()

    def add_user(self, email="existing@klu.ac.in", google_subject=None):
        with self.app.app_context():
            user = User(
                name="Existing Student",
                registration_number="REG-100",
                university_email=email,
                department="CSE",
                section="A",
                role="student",
                is_verified=True,
                is_active=True,
                google_subject=google_subject,
            )
            user.set_password("StrongPass123")
            db.session.add(user)
            db.session.commit()
            return user.id

    def find_user(self, **criteria):
        with self.app.app_context():
            return User.query.filter_by(**criteria).first()

    def user_count(self):
        with self.app.app_context():
            return User.query.count()

    def callback_with_profile(self, profile):
        fake_google = FakeGoogleClient(profile=profile)
        with patch("app.auth.routes._google_client", return_value=fake_google):
            return self.client.get("/login/google/callback")

    @staticmethod
    def accepted_email_response():
        return Mock(status_code=200)

    def test_existing_email_password_login_and_registration_still_work(self):
        self.add_user()
        login_response = self.client.post(
            "/login?next=https://attacker.example",
            data={"email": "existing@klu.ac.in", "password": "StrongPass123"},
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.location, "/")

        registration_client = self.app.test_client()
        registration_response = registration_client.post(
            "/register",
            data={
                "name": "New Student",
                "registration_number": "REG-200",
                "university_email": "new@klu.ac.in",
                "department": "CSE",
                "section": "A",
                "phone": "9876543210",
                "password": "StrongPass123",
                "confirm_password": "StrongPass123",
            },
        )
        self.assertEqual(registration_response.status_code, 302)
        self.assertIsNotNone(self.find_user(university_email="new@klu.ac.in"))

    def test_google_start_redirects_to_provider(self):
        fake_google = FakeGoogleClient()
        with patch("app.auth.routes._google_client", return_value=fake_google):
            response = self.client.get("/login/google")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.startswith("https://accounts.google.com/"))

    def test_login_and_registration_use_the_same_google_sign_in_route(self):
        for page in ("/login", "/register"):
            with self.subTest(page=page):
                response = self.client.get(page)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'href="/login/google"', response.data)
                self.assertIn(b"Continue with Google", response.data)

        with patch(
            "app.auth.routes._google_client",
            return_value=FakeGoogleClient(),
        ) as create_client:
            login_response = self.client.get("/login/google")
            register_response = self.client.get("/login/google")
        self.assertEqual(login_response.location, register_response.location)
        self.assertEqual(create_client.call_count, 2)

    def test_missing_google_configuration_names_required_variables_safely(self):
        self.app.config["GOOGLE_CLIENT_ID"] = None
        self.app.config["GOOGLE_CLIENT_SECRET"] = None
        with patch("app.auth.routes._google_client") as create_client:
            response = self.client.get("/login/google", follow_redirects=True)
        self.assertIn(b"GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET", response.data)
        self.assertNotIn(b"Please use email and password", response.data)
        create_client.assert_not_called()

    def test_marketplace_home_and_browse_pages_still_render(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/products").status_code, 200)

    def test_verified_google_profile_creates_student_and_repeat_login_reuses_it(self):
        profile = {
            "sub": "google-sub-123",
            "email": "newstudent@klu.ac.in",
            "email_verified": True,
            "name": "New Google Student",
            "picture": "https://example.test/profile.png",
        }
        self.callback_with_profile(profile)
        user = self.find_user(google_subject="google-sub-123")
        user_id = user.id
        self.assertEqual(user.university_email, "newstudent@klu.ac.in")
        self.assertEqual(user.name, "New Google Student")
        self.assertEqual(user.google_picture_url, "https://example.test/profile.png")
        self.assertEqual(user.role, "student")
        self.assertFalse(user.is_verified)
        self.assertEqual(self.user_count(), 1)

        with self.client.session_transaction() as session:
            session.pop("_user_id", None)
        self.callback_with_profile(profile)
        self.assertEqual(self.user_count(), 1)
        with self.client.session_transaction() as session:
            self.assertEqual(session["_user_id"], str(user_id))

    def test_new_google_student_gets_registration_emails_only_once(self):
        self.app.config.update(
            RESEND_API_KEY="re_test_key",
            RESEND_FROM="notifications@example.com",
            ADMIN_NOTIFICATION_EMAIL="admin-notifications@example.com",
        )
        profile = {
            "sub": "google-sub-registration-notice",
            "email": "newgoogle@klu.ac.in",
            "email_verified": True,
            "name": "New Google Student",
        }
        with patch(
            "app.email_notifications.requests.post",
            return_value=self.accepted_email_response(),
        ) as send:
            first_response = self.callback_with_profile(profile)
            self.assertEqual(send.call_count, 2)
            repeated_response = self.callback_with_profile(profile)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(repeated_response.status_code, 302)
        self.assertEqual(send.call_count, 2)

    def test_verified_email_links_existing_account_but_unverified_email_does_not(self):
        user_id = self.add_user()
        response = self.callback_with_profile(
            {
                "sub": "verified-sub",
                "email": "existing@klu.ac.in",
                "email_verified": True,
                "name": "Existing Student",
            }
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user_count(), 1)
        self.assertEqual(self.find_user(id=user_id).google_subject, "verified-sub")

        with self.client.session_transaction() as session:
            session.pop("_user_id", None)
        rejected = self.callback_with_profile(
            {
                "sub": "unverified-sub",
                "email": "another@klu.ac.in",
                "email_verified": False,
                "name": "Unverified Student",
            }
        )
        self.assertEqual(rejected.status_code, 302)
        self.assertEqual(self.user_count(), 1)
        self.assertIsNone(self.find_user(google_subject="unverified-sub"))

    def test_cancelled_and_failed_google_authentication_are_handled(self):
        cancelled = self.client.get("/login/google/callback?error=access_denied")
        self.assertEqual(cancelled.status_code, 302)

        fake_google = FakeGoogleClient(error=ValueError("invalid test response"))
        with patch("app.auth.routes._google_client", return_value=fake_google):
            failed = self.client.get("/login/google/callback")
        self.assertEqual(failed.status_code, 302)
        self.assertEqual(self.user_count(), 0)

    def test_google_sign_in_rejects_non_university_email_and_external_next_url(self):
        with patch(
            "app.auth.routes._google_client",
            return_value=FakeGoogleClient(),
        ) as create_client:
            response = self.client.get("/login/google?next=https://attacker.example")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/login"))
        create_client.assert_not_called()
        login_page = self.client.get(response.location)
        self.assertIn(b"requested sign-in destination is invalid", login_page.data)

        profile_response = self.callback_with_profile(
            {
                "sub": "external-sub",
                "email": "student@gmail.com",
                "email_verified": True,
                "name": "External Student",
            }
        )
        self.assertEqual(profile_response.status_code, 302)
        self.assertEqual(self.user_count(), 0)

    def test_existing_logout_flow_still_works(self):
        self.add_user()
        self.client.post(
            "/login",
            data={"email": "existing@klu.ac.in", "password": "StrongPass123"},
        )
        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("_user_id", session)

    def test_z_legacy_user_schema_is_migrated_without_losing_users(self):
        original_id = self.add_user()
        with self.app.app_context():
            db.session.execute(text("DROP INDEX uq_users_google_subject"))
            db.session.execute(text("ALTER TABLE users DROP COLUMN google_subject"))
            db.session.execute(text("ALTER TABLE users DROP COLUMN google_picture_url"))
            db.session.commit()

            ensure_database_schema()
            migrated_user = db.session.get(User, original_id)
            columns = {column["name"] for column in db.inspect(db.engine).get_columns("users")}
            self.assertIn("google_subject", columns)
            self.assertIn("google_picture_url", columns)
            self.assertEqual(migrated_user.university_email, "existing@klu.ac.in")
