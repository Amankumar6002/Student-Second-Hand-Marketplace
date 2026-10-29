import unittest
import requests
from unittest.mock import Mock, patch

from app import create_app
from app.extensions import db
from app.models import User


class RegistrationDatabaseTests(unittest.TestCase):
    @staticmethod
    def _accepted_response():
        return Mock(status_code=200)

    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            RESEND_API_KEY="re_test_key",
            RESEND_FROM="notifications@example.com",
            ADMIN_NOTIFICATION_EMAIL="admin-notifications@example.com",
            PUBLIC_BASE_URL="https://marketplace.example.test",
        )
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
        with patch(
            "app.email_notifications.requests.post",
            return_value=self._accepted_response(),
        ) as send:
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
        self.assertEqual(send.call_count, 2)
        student_payload = send.call_args_list[0].kwargs["json"]
        admin_payload = send.call_args_list[1].kwargs["json"]
        self.assertEqual(
            send.call_args_list[0].kwargs["headers"]["Authorization"],
            "Bearer re_test_key",
        )
        self.assertEqual(student_payload["to"], ["newstudent@klu.ac.in"])
        self.assertEqual(
            student_payload["subject"],
            "Your Student Second-Hand Marketplace Account Has Been Created",
        )
        self.assertIn("Hello New Student", student_payload["text"])
        self.assertIn("awaiting administrator verification", student_payload["text"])
        self.assertEqual(
            admin_payload["to"],
            ["admin-notifications@example.com"],
        )
        self.assertEqual(
            admin_payload["subject"],
            "New Student Registration — Verification Required",
        )
        self.assertIn("newstudent@klu.ac.in", admin_payload["text"])
        self.assertIn("Registration Date:", admin_payload["text"])
        self.assertIn(
            "https://marketplace.example.test/admin/users",
            admin_payload["text"],
        )
        self.assertTrue(all(call.kwargs["timeout"] == 8 for call in send.call_args_list))
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

    def test_failed_registration_does_not_send_registration_notifications(self):
        registration_data = {
            'name': 'New Student',
            'registration_number': 'REG-900',
            'university_email': 'newstudent@klu.ac.in',
            'department': 'CSE',
            'section': 'A',
            'phone': '9876543210',
            'password': 'StrongPass123',
            'confirm_password': 'StrongPass123',
        }
        with patch(
            "app.email_notifications.requests.post",
            return_value=self._accepted_response(),
        ) as send:
            invalid = dict(registration_data, university_email="outside@example.test")
            failed = self.client.post('/register', data=invalid)
            self.assertEqual(failed.status_code, 200)
            send.assert_not_called()
            successful = self.client.post('/register', data=registration_data)
            self.assertEqual(successful.status_code, 302)
            self.assertEqual(send.call_count, 2)
            repeated = self.client.post('/register', data=registration_data)

        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(send.call_count, 2)

    def test_email_failure_does_not_undo_registration(self):
        with self.assertLogs("app", level="WARNING"):
            with patch(
                "app.email_notifications.requests.post",
                side_effect=requests.ConnectionError("private provider response"),
            ) as send:
                response = self.client.post(
                    '/register',
                    data={
                        'name': 'New Student',
                        'registration_number': 'REG-901',
                        'university_email': 'newstudent2@klu.ac.in',
                        'department': 'CSE',
                        'section': 'A',
                        'phone': '9876543210',
                        'password': 'StrongPass123',
                        'confirm_password': 'StrongPass123',
                    },
                )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(send.call_count, 2)
        with self.app.app_context():
            user = User.query.filter_by(
                university_email='newstudent2@klu.ac.in'
            ).one()
            self.assertFalse(user.is_verified)
            self.assertTrue(user.is_active)
        with self.client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        self.assertIn(
            (
                "success",
                "Account created. An administrator will verify your student status.",
            ),
            flashes,
        )
        self.assertIn(
            (
                "warning",
                "One or more registration notification emails could not be sent. "
                "Your account was still created successfully.",
            ),
            flashes,
        )


if __name__ == '__main__':
    unittest.main()
