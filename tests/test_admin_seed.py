import os
import unittest
from unittest.mock import patch

from app import create_app, seed_default_admin
from app.extensions import db
from app.models import User
from config import Config


class AdminSeedTests(unittest.TestCase):
    class TestConfig(Config):
        TESTING = False
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    def _create_app(self):
        self.app = create_app(self.TestConfig)
        return self.app

    def tearDown(self):
        if hasattr(self, "app"):
            with self.app.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_missing_password_skips_admin_creation(self):
        with patch.dict(os.environ):
            os.environ.pop("DEFAULT_ADMIN_PASSWORD", None)
            app = self._create_app()

        with app.app_context():
            self.assertIsNone(
                User.query.filter_by(university_email="admin@klu.ac.in").first()
            )

    def test_admin_is_created_from_environment_password(self):
        with patch.dict(os.environ, {"DEFAULT_ADMIN_PASSWORD": "TestAdminPass123"}):
            app = self._create_app()

        with app.app_context():
            admin = User.query.filter_by(university_email="admin@klu.ac.in").first()
            self.assertIsNotNone(admin)
            self.assertTrue(admin.check_password("TestAdminPass123"))
            self.assertEqual(admin.role, "admin")

    def test_existing_admin_password_is_not_changed(self):
        with patch.dict(os.environ, {"DEFAULT_ADMIN_PASSWORD": "InitialPass123"}):
            app = self._create_app()

        with app.app_context():
            admin = User.query.filter_by(university_email="admin@klu.ac.in").first()
            admin.set_password("ExistingPass123")
            db.session.commit()

            with patch.dict(os.environ, {"DEFAULT_ADMIN_PASSWORD": "NewPass123"}):
                result = seed_default_admin()

            self.assertEqual(result.id, admin.id)
            self.assertTrue(admin.check_password("ExistingPass123"))
            self.assertFalse(admin.check_password("NewPass123"))


if __name__ == "__main__":
    unittest.main()
