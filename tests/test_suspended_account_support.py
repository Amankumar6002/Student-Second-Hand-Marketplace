import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

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
    PUBLIC_BASE_URL = "https://marketplace.example.test"
    RESEND_API_KEY = "re_test_key"
    RESEND_FROM = "notifications@example.com"


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

    @staticmethod
    def _accepted_response():
        response = Mock(status=200)
        response.read.return_value = b'{"id":"email-test-id"}'
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context

    def test_suspend_commits_then_emails_student_with_support_address(self):
        self._login_admin()

        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            def assert_suspension_committed(request, timeout):
                with self.app.app_context():
                    user = db.session.get(User, self.student_id)
                    self.assertFalse(user.is_active)
                self.assertEqual(timeout, 8)
                return self._accepted_response()

            send.side_effect = assert_suspension_committed
            response = self._moderate("suspend")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], ["student@klu.ac.in"])
        self.assertEqual(payload["from"], "notifications@example.com")
        self.assertIn("Test Student", payload["text"])
        self.assertIn("suspended", payload["text"])
        self.assertIn("support@example.test", payload["text"])
        self.assertIn("request a review", payload["text"])
        self.assertNotIn("StrongPass123", payload["text"])
        with self.app.app_context():
            self.assertFalse(db.session.get(User, self.student_id).is_active)

    def test_repeat_suspend_does_not_send_duplicate_email(self):
        self._login_admin()

        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            first_response = self._moderate("suspend")
            repeated_response = self._moderate("suspend")

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(repeated_response.status_code, 302)
        send.assert_called_once()

    def test_provider_failure_does_not_revert_suspension_or_leak_error(self):
        self._login_admin()

        with self.assertLogs("app", level="WARNING") as captured_logs:
            with patch(
                "app.email_notifications.urlopen",
                side_effect=URLError("private provider response must not be logged"),
            ) as send:
                response = self._moderate("suspend")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        output = "\n".join(captured_logs.output)
        self.assertIn("Email API request failed", output)
        self.assertNotIn("private provider response", output)
        with self.client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        self.assertIn(("success", "User suspended."), flashes)
        self.assertIn(
            (
                "warning",
                "The suspension notification email could not be sent. "
                "Check the Resend configuration and server logs.",
            ),
            flashes,
        )
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
        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            def assert_activation_committed(request, timeout):
                with self.app.app_context():
                    student = db.session.get(User, self.student_id)
                    self.assertTrue(student.is_active)
                self.assertEqual(timeout, 8)
                return self._accepted_response()

            send.side_effect = assert_activation_committed
            response = self._moderate("activate")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(
            payload["subject"],
            "Your Student Second-Hand Marketplace Account Has Been Reactivated",
        )
        self.assertEqual(payload["to"], ["student@klu.ac.in"])
        self.assertEqual(request.get_header("Authorization"), "Bearer re_test_key")
        self.assertIn("Hello Test Student,", payload["text"])
        self.assertIn("reactivated by the administrator", payload["text"])
        self.assertIn("You can now log in again", payload["text"])
        self.assertIn("support@example.test", payload["text"])
        with self.client.session_transaction() as session:
            self.assertIn(
                ("success", "User activated."),
                session.get("_flashes", []),
            )
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertTrue(student.is_active)
            self.assertTrue(student.is_verified)
            self.assertEqual(student.role, "student")

    def test_reactivating_active_account_does_not_send_duplicate_email(self):
        self._login_admin()
        with patch("app.email_notifications.urlopen") as send:
            response = self._moderate("activate")

        self.assertEqual(response.status_code, 302)
        send.assert_not_called()

    def test_verification_does_not_activate_a_suspended_account(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            student.is_verified = False
            db.session.commit()

        self._login_admin()
        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            response = self._moderate("verify")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        payload = json.loads(send.call_args.args[0].data)
        self.assertIn("Verified", payload["subject"])
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertFalse(student.is_active)
            self.assertTrue(student.is_verified)

    def test_admin_verification_commits_and_sends_marketplace_access_email(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_verified = False
            db.session.commit()

        self._login_admin()
        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            response = self._moderate("verify")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], ["student@klu.ac.in"])
        self.assertEqual(
            payload["subject"],
            "Your Student Second-Hand Marketplace Account Has Been Verified!",
        )
        self.assertIn("You can now access the marketplace", payload["text"])
        self.assertIn("https://marketplace.example.test", payload["text"])
        self.assertEqual(send.call_args.kwargs["timeout"], 8)
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertTrue(student.is_verified)
            self.assertTrue(student.is_active)
        with self.client.session_transaction() as session:
            self.assertIn(
                ("success", "User verification updated."),
                session.get("_flashes", []),
            )

    def test_repeated_verification_does_not_send_duplicate_email(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_verified = False
            db.session.commit()

        self._login_admin()
        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            first = self._moderate("verify")
            repeated = self._moderate("verify")

        self.assertEqual(first.status_code, 302)
        self.assertEqual(repeated.status_code, 302)
        send.assert_called_once()

    def test_verification_email_failure_does_not_undo_verification(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_verified = False
            db.session.commit()

        self._login_admin()
        with self.assertLogs("app", level="WARNING"):
            with patch(
                "app.email_notifications.urlopen",
                side_effect=URLError("private provider response"),
            ) as send:
                response = self._moderate("verify")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        with self.app.app_context():
            self.assertTrue(db.session.get(User, self.student_id).is_verified)
        with self.client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        self.assertIn(("success", "User verification updated."), flashes)
        self.assertIn(
            (
                "warning",
                "The verification notification email could not be sent. "
                "Check the Resend configuration and server logs.",
            ),
            flashes,
        )

    def test_verifying_suspended_student_does_not_activate_account(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_verified = False
            student.is_active = False
            db.session.commit()

        self._login_admin()
        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            response = self._moderate("verify")

        self.assertEqual(response.status_code, 302)
        payload = json.loads(send.call_args.args[0].data)
        self.assertIn("remains suspended", payload["text"])
        self.assertNotIn("You can now access the marketplace", payload["text"])
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertTrue(student.is_verified)
            self.assertFalse(student.is_active)

    def test_reactivation_email_failure_does_not_undo_activation(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            db.session.commit()

        self._login_admin()
        with self.assertLogs("app", level="WARNING") as captured_logs:
            with patch(
                "app.email_notifications.urlopen",
                side_effect=TimeoutError("private provider response must not be logged"),
            ) as send:
                response = self._moderate("activate")

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        output = "\n".join(captured_logs.output)
        self.assertIn("Email API request failed", output)
        self.assertNotIn("private provider response", output)
        with self.client.session_transaction() as session:
            flashes = session.get("_flashes", [])
            self.assertIn(
                ("success", "User activated."),
                flashes,
            )
            self.assertIn(
                (
                    "warning",
                    "The activation notification email could not be sent. "
                    "Check the Resend configuration and server logs.",
                ),
                flashes,
            )
        with self.app.app_context():
            self.assertTrue(db.session.get(User, self.student_id).is_active)

    def test_reactivation_notification_skips_invalid_recipient(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.university_email = "not-an-email"
            db.session.commit()

            with patch("app.email_notifications.urlopen") as send:
                self.assertFalse(notify_student_account_activated(student))

        send.assert_not_called()

    def test_missing_resend_configuration_skips_request(self):
        self.app.config.update(RESEND_API_KEY=None, RESEND_FROM=None)

        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            with patch("app.email_notifications.urlopen") as send:
                self.assertFalse(notify_student_account_activated(student))

        send.assert_not_called()

    def test_resend_authentication_errors_are_reported_as_failures(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            for status in (401, 403):
                with self.subTest(status=status):
                    error = HTTPError(
                        "https://api.resend.com/emails",
                        status,
                        "Rejected",
                        None,
                        None,
                    )
                    with patch(
                        "app.email_notifications.urlopen",
                        side_effect=error,
                    ):
                        self.assertFalse(
                            notify_student_account_activated(student)
                        )

    def test_reactivated_student_can_log_in_again(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.is_active = False
            db.session.commit()

        self._login_admin()
        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ):
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
        with patch("app.email_notifications.urlopen") as send:
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
