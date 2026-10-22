import unittest

from app import create_app
from app.extensions import db
from app.models import User


class AdminSeedTests(unittest.TestCase):
    def test_default_admin_is_created_on_startup(self):
        app = create_app()
        with app.app_context():
            db.drop_all()
            db.create_all()
            admin = User.query.filter_by(university_email='admin@klu.ac.in').first()
            self.assertIsNotNone(admin)
            self.assertTrue(admin.check_password('ChangeMe123!'))
            self.assertEqual(admin.role, 'admin')


if __name__ == '__main__':
    unittest.main()
