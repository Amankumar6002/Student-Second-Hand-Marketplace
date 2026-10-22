import unittest

from app import create_app
from app.extensions import db
from app.models import User


class RegistrationDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()
            admin = User(
                name='Marketplace Admin',
                registration_number='ADMIN-001',
                university_email='admin@klu.ac.in',
                department='Administration',
                section='A',
                role='admin',
                is_verified=True,
                is_active=True,
            )
            admin.set_password('ChangeMe123!')
            db.session.add(admin)
            db.session.commit()

    def test_register_persists_user_to_same_root_marketplace_db(self):
        response = self.client.post(
            '/register',
            data={
                'name': 'New Student',
                'registration_number': 'REG-900',
                'university_email': 'newstudent@klu.ac.in',
                'department': 'CSE',
                'section': 'A',
                'phone': '9876543210',
                'password': 'StrongPass123',
                'confirm_password': 'StrongPass123',
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(university_email='newstudent@klu.ac.in').first()
            self.assertIsNotNone(user)
            self.assertEqual(user.name, 'New Student')
            self.assertEqual(user.role, 'student')
            self.assertFalse(user.is_verified)
            self.assertTrue(user.is_active)
            self.assertIsNotNone(user.password_hash)
            self.assertNotEqual(user.password_hash, 'StrongPass123')
            self.assertEqual(self.app.config['SQLALCHEMY_DATABASE_URI'].split('sqlite:///')[-1], 'C:/Users/vikas/Student Second Hand/marketplace.db')


if __name__ == '__main__':
    unittest.main()
