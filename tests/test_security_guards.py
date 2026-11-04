import unittest

from app import create_app
from app.extensions import db
from app.models import User
from config import Config


class SecurityGuardTests(unittest.TestCase):
    class TestConfig(Config):
        TESTING = True
        IS_PRODUCTION = False
        SECRET_KEY = "test-only-secret-key"
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    class MissingProductionSecretConfig(Config):
        TESTING = True
        IS_PRODUCTION = True
        SECRET_KEY = None
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    class WeakProductionSecretConfig(Config):
        TESTING = True
        IS_PRODUCTION = True
        SECRET_KEY = "too-short"
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    def setUp(self):
        self.app = create_app(self.TestConfig)
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()
            self.admin = self._add_user(
                name="Admin User",
                registration_number="ADMIN-SECURITY",
                email="admin-security@klu.ac.in",
                role="admin",
                is_active=True,
            )
            self.student = self._add_user(
                name="Student User",
                registration_number="STUDENT-SECURITY",
                email="student-security@klu.ac.in",
                role="student",
                is_active=True,
            )
            self.admin_id = self.admin.id
            self.student_id = self.student.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    @staticmethod
    def _add_user(name, registration_number, email, role, is_active):
        user = User(
            name=name,
            registration_number=registration_number,
            university_email=email,
            department="CSE",
            section="A",
            role=role,
            is_verified=True,
            is_active=is_active,
        )
        user.set_password("TestPassword123")
        db.session.add(user)
        db.session.commit()
        return user

    def _set_authenticated_user(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def test_missing_production_secret_fails_app_startup(self):
        with self.assertRaisesRegex(RuntimeError, "SECRET_KEY must be configured"):
            create_app(self.MissingProductionSecretConfig)

    def test_weak_production_secret_fails_app_startup(self):
        with self.assertRaisesRegex(RuntimeError, "at least 32 characters"):
            create_app(self.WeakProductionSecretConfig)

    def test_local_config_uses_a_secret_instead_of_the_known_fallback(self):
        self.assertIsInstance(Config.SECRET_KEY, str)
        self.assertGreaterEqual(len(Config.SECRET_KEY), 32)
        self.assertNotEqual(Config.SECRET_KEY, "development-only-change-me")

    def test_active_admin_can_access_admin_store_and_orders(self):
        self._set_authenticated_user(self.admin_id)

        store_response = self.client.get("/klu-store/admin/manage")
        orders_response = self.client.get("/orders/admin/all-orders")

        self.assertEqual(store_response.status_code, 200)
        self.assertEqual(orders_response.status_code, 200)

    def test_student_cannot_access_admin_store_or_orders(self):
        self._set_authenticated_user(self.student_id)

        store_response = self.client.get("/klu-store/admin/manage")
        orders_response = self.client.get("/orders/admin/all-orders")

        self.assertEqual(store_response.status_code, 403)
        self.assertEqual(orders_response.status_code, 403)

    def test_suspended_admin_with_existing_session_is_denied(self):
        self._set_authenticated_user(self.admin_id)
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            admin.is_active = False
            db.session.commit()

        store_response = self.client.get("/klu-store/admin/manage")
        orders_response = self.client.get("/orders/admin/all-orders")

        self.assertEqual(store_response.status_code, 302)
        self.assertEqual(orders_response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
