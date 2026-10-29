import smtplib
import unittest
from unittest.mock import patch

from app import create_app
from app.email_notifications import notify_student_account_activated
from app.extensions import db
from app.models import User
from config import Config


class SuspendedAccountTestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SUPPORT_EMAIL = "support@example.test"


class SuspendedAccountSupportTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(SuspendedAccountTestConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()
            self.admin = self._add_user(
                name="Marketplace Admin",
                registration_number="ADMIN-001",
                email="admin@klu.ac.in",
                role="admin",
            )
            self.student = self._add_user(
                name="Test Student",
                registration_number="STUDENT-001",
                email="student@klu.ac.in",
            )
            self.student_id = self.student.id
            self.admin_id = self.admin.id

    @staticmethod
    def _add_user(name, registration_number, email, role="student"):
        user = User(
            name=name,
            registration_number=registration_number,
            university_email=email,
            department="CSE",
            section="A",
            role=role,
            is_verified=True,
            is_active=True,
        )
        user.set_password("StrongPass123")
        db.session.add(user)
        db.session.commit()
        return user

    def _login_admin(self):
        return self.client.post(
            "/login",
            data={"email": "admin@klu.ac.in", "password": "StrongPass123"},
        )

    def _moderate(self, action, user_id=None):
        return self.client.post(
            f"/admin/users/{user_id or self.student_id}/{action}"
        )

    def test_suspend_commits_then_emails_student_with_support_address(self):
        self._login_admin()

        with patch("app.email_notifications.mail.send") as send:
            def assert_suspension_committed(message):
                with self.app.app_context():
                    user = db.session.get(User, self.student_id)
                    self.assertFalse(user.is_active)

            send.side_effect = assert_suspension_committed
            response = self._moderate("suspend")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        message = send.call_args.args[0]
        self.assertEqual(message.recipients, ["student@klu.ac.in"])
        self.assertIn("Test Student", message.body)
        self.assertIn("suspended", message.body)
        self.assertIn("support@example.test", message.body)
        self.assertIn("request a review", message.body)
        self.assertNotIn("StrongPass123", message.body)
        with self.app.app_context():
            self.assertFalse(db.session.get(User, self.student_id).is_active)

    def test_repeat_suspend_does_not_send_duplicate_email(self):
        self._login_admin()

        with patch("app.email_notifications.mail.send") as send:
            first_response = self._moderate("suspend")
            repeated_response = self._moderate("suspend")

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(repeated_response.status_code, 302)
        send.assert_called_once()

    def test_smtp_failure_does_not_revert_suspension_or_leak_error(self):
        self._login_admin()

        with self.assertLogs("app", level="WARNING") as captured_logs:
            with patch(
                "app.email_notifications.mail.send",
                side_effect=smtplib.SMTPServerDisconnected(
                    "private SMTP response must not be logged"
                ),
            ) as send:
                response = self._moderate("suspend")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        output = "\n".join(captured_logs.output)
        self.assertIn("Account suspension email failed", output)
        self.assertNotIn("private SMTP response", output)
        with self.app.app_context():
            self.assertFalse(db.session.get(User, self.student_id).is_active)

    def test_suspended_student_sees_support_mailto_and_cannot_access_profile(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            db.session.commit()

        response = self.client.post(
            "/login",
            data={"email": "student@klu.ac.in", "password": "StrongPass123"},
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Your account has been suspended", page)
        self.assertIn("mailto:support%40example.test", page)
        self.assertIn("Account%20Suspension%20Appeal", page)
        profile_response = self.client.get("/profile")
        self.assertEqual(profile_response.status_code, 302)
        self.assertIn("/login", profile_response.location)

    def test_wrong_password_does_not_disclose_suspension(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            db.session.commit()

        response = self.client.post(
            "/login",
            data={"email": "student@klu.ac.in", "password": "wrong-password"},
        )

        page = response.get_data(as_text=True)
        self.assertIn("Invalid credentials.", page)
        self.assertNotIn("Your account has been suspended", page)

    def test_admin_can_reactivate_and_email_student_after_commit(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            db.session.commit()

        self._login_admin()
        with patch("app.email_notifications.mail.send") as send:
            def assert_activation_committed(message):
                with self.app.app_context():
                    student = db.session.get(User, self.student_id)
                    self.assertTrue(student.is_active)

            send.side_effect = assert_activation_committed
            response = self._moderate("activate")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        message = send.call_args.args[0]
        self.assertEqual(
            message.subject,
            "Your Student Second-Hand Marketplace Account Has Been Reactivated",
        )
        self.assertEqual(message.recipients, ["student@klu.ac.in"])
        self.assertEqual(message.sender, self.app.config["MAIL_DEFAULT_SENDER"])
        self.assertIn("Hello Test Student,", message.body)
        self.assertIn("reactivated by the administrator", message.body)
        self.assertIn("You can now log in again", message.body)
        self.assertIn("support@example.test", message.body)
        with self.client.session_transaction() as session:
            self.assertIn(
                ("success", "User activated and reactivation email sent."),
                session.get("_flashes", []),
            )
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertTrue(student.is_active)
            self.assertTrue(student.is_verified)
            self.assertEqual(student.role, "student")

    def test_reactivating_active_account_does_not_send_duplicate_email(self):
        self._login_admin()
        with patch("app.email_notifications.mail.send") as send:
            response = self._moderate("activate")

        self.assertEqual(response.status_code, 302)
        send.assert_not_called()

    def test_verify_action_does_not_send_reactivation_email(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            student.is_verified = False
            db.session.commit()

        self._login_admin()
        with patch("app.email_notifications.mail.send") as send:
            response = self._moderate("verify")

        self.assertEqual(response.status_code, 302)
        send.assert_not_called()
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertFalse(student.is_active)
            self.assertTrue(student.is_verified)

    def test_reactivation_email_failure_does_not_undo_activation(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            db.session.commit()

        self._login_admin()
        with self.assertLogs("app", level="WARNING") as captured_logs:
            with patch(
                "app.email_notifications.mail.send",
                side_effect=smtplib.SMTPServerDisconnected(
                    "private SMTP response must not be logged"
                ),
            ) as send:
                response = self._moderate("activate")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        output = "\n".join(captured_logs.output)
        self.assertIn("Account reactivation email failed", output)
        self.assertNotIn("private SMTP response", output)
        with self.client.session_transaction() as session:
            self.assertIn(
                (
                    "warning",
                    "User activated, but the reactivation email could not be sent. "
                    "Check the mail configuration and server logs.",
                ),
                session.get("_flashes", []),
            )
        with self.app.app_context():
            self.assertTrue(db.session.get(User, self.student_id).is_active)

    def test_reactivation_notification_skips_invalid_recipient(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.university_email = "not-an-email"
            db.session.commit()

            with patch("app.email_notifications.mail.send") as send:
                self.assertFalse(notify_student_account_activated(student))

        send.assert_not_called()

    def test_reactivated_student_can_log_in_again(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            db.session.commit()

        self._login_admin()
        with patch("app.email_notifications.mail.send"):
            self._moderate("activate")

        response = self.client.post(
            "/login",
            data={"email": "student@klu.ac.in", "password": "StrongPass123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(self.client.get("/profile").status_code, 200)

    def test_unauthorized_and_unsupported_actions_do_not_change_user(self):
        unauthorized = self._moderate("suspend")
        self.assertEqual(unauthorized.status_code, 302)

        student_client = self.app.test_client()
        student_client.post(
            "/login",
            data={"email": "student@klu.ac.in", "password": "StrongPass123"},
        )
        forbidden = student_client.post(f"/admin/users/{self.student_id}/suspend")
        self.assertEqual(forbidden.status_code, 403)

        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            db.session.commit()

            self._add_user(
                name="Another Student",
                registration_number="STUDENT-002",
                email="another-student@klu.ac.in",
            )
        attacker_client = self.app.test_client()
        attacker_client.post(
            "/login",
            data={
                "email": "another-student@klu.ac.in",
                "password": "StrongPass123",
            },
        )
        forbidden_activation = attacker_client.post(
            f"/admin/users/{self.student_id}/activate"
        )
        self.assertEqual(forbidden_activation.status_code, 403)
        with self.app.app_context():
            self.assertFalse(db.session.get(User, self.student_id).is_active)

        self._login_admin()
        with patch("app.email_notifications.mail.send") as send:
            unsupported = self._moderate("delete")

        self.assertEqual(unsupported.status_code, 400)
        send.assert_not_called()
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertFalse(student.is_active)

    def test_csrf_is_required_for_suspension(self):
        self._login_admin()
        self.app.config["WTF_CSRF_ENABLED"] = True

        response = self._moderate("suspend")

        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertTrue(db.session.get(User, self.student_id).is_active)


if __name__ == "__main__":
    unittest.main()
