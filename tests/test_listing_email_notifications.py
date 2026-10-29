import json
import unittest
from decimal import Decimal
from urllib.error import URLError
from unittest.mock import Mock, patch

from app import create_app
from app.extensions import db
from app.models import Category, Product, User
from config import Config


class ListingEmailTestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    MAIL_USERNAME = "admin@example.com"
    MAIL_PASSWORD = "test-password"
    MAIL_DEFAULT_SENDER = "admin@example.com"
    ADMIN_NOTIFICATION_EMAIL = "admin@example.com"
    SUPPORT_EMAIL = None
    RESEND_API_KEY = "re_test_key"
    RESEND_FROM = "notifications@example.com"


class ListingEmailNotificationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(ListingEmailTestConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()
            self.category = Category(name="Books")
            student = User(
                name="Test Student",
                registration_number="STUDENT-001",
                university_email="student@klu.ac.in",
                department="CSE",
                section="A",
                role="student",
                is_verified=True,
                is_active=True,
            )
            student.set_password("StudentPass123")
            admin = User(
                name="Marketplace Admin",
                registration_number="ADMIN-001",
                university_email="admin@klu.ac.in",
                department="Administration",
                section="A",
                role="admin",
                is_verified=True,
                is_active=True,
            )
            admin.set_password("AdminPass123")
            db.session.add_all([self.category, student, admin])
            db.session.commit()
            self.category_id = self.category.id

    def _login(self, email, password):
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )

    def _create_listing(self, title="Test Textbook"):
        return self.client.post(
            "/product/create",
            data={
                "title": title,
                "description": "A used textbook in good condition.",
                "category_id": str(self.category_id),
                "price": "250.00",
                "listing_type": "sale",
                "condition": "Good",
                "location": "Campus",
                "availability": "Weekdays",
            },
            follow_redirects=False,
        )

    @staticmethod
    def _accepted_response():
        response = Mock(status=200)
        response.read.return_value = b'{"id":"email-test-id"}'
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context

    def test_listing_is_committed_pending_before_admin_email(self):
        self._login("student@klu.ac.in", "StudentPass123")

        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            def assert_listing_was_committed(request, timeout):
                with self.app.app_context():
                    product = Product.query.one()
                    self.assertEqual(product.approval_status, "pending")
                self.assertEqual(timeout, 8)
                return self._accepted_response()

            send.side_effect = assert_listing_was_committed
            response = self._create_listing()

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer re_test_key")
        self.assertEqual(payload["to"], ["admin@example.com"])
        self.assertEqual(payload["from"], "notifications@example.com")
        self.assertEqual(payload["subject"], "Student listing waiting for approval")
        self.assertIn("Test Textbook", payload["text"])
        self.assertIn("250.00", payload["text"])
        self.assertIn("Books", payload["text"])
        self.assertIn("Test Student", payload["text"])
        self.assertIn("/admin/products", payload["text"])
        with self.app.app_context():
            product = Product.query.one()
            self.assertEqual(product.approval_status, "pending")
            self.assertEqual(product.title, "Test Textbook")

    def test_email_failure_keeps_one_pending_listing_and_refresh_does_not_resend(self):
        self._login("student@klu.ac.in", "StudentPass123")

        with self.assertLogs("app", level="WARNING") as captured_logs:
            with patch(
                "app.email_notifications.urlopen",
                side_effect=URLError("private provider response must not be logged"),
            ) as send:
                response = self._create_listing()
                self.assertEqual(response.status_code, 302)
                self.client.get(response.headers["Location"])
                send.assert_called_once()
        self.assertNotIn(
            "private provider response must not be logged",
            "\n".join(captured_logs.output),
        )

        with self.app.app_context():
            products = Product.query.all()
            self.assertEqual(len(products), 1)
            self.assertEqual(products[0].approval_status, "pending")

    def test_listing_edit_does_not_send_another_submission_notification(self):
        self._login("student@klu.ac.in", "StudentPass123")
        self._create_listing()
        with self.app.app_context():
            product_id = Product.query.one().id

        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            response = self.client.post(
                f"/product/{product_id}/edit",
                data={
                    "title": "Updated Textbook",
                    "description": "Updated description.",
                    "category_id": str(self.category_id),
                    "price": "200.00",
                    "listing_type": "sale",
                    "condition": "Good",
                    "location": "Campus",
                },
            )

        self.assertEqual(response.status_code, 302)
        send.assert_not_called()
        with self.app.app_context():
            self.assertEqual(Product.query.count(), 1)
            self.assertEqual(Product.query.one().approval_status, "pending")

    def test_admin_moderation_notifies_student_only_when_status_changes(self):
        with self.app.app_context():
            product = Product(
                seller_id=User.query.filter_by(role="student").one().id,
                category_id=self.category_id,
                title="Moderated Textbook",
                description="Description",
                price=Decimal("100.00"),
                listing_type="sale",
                condition="Good",
                location="Campus",
            )
            db.session.add(product)
            db.session.commit()
            product_id = product.id

        self._login("student@klu.ac.in", "StudentPass123")
        unauthorized = self.client.post(f"/admin/products/{product_id}/approve")
        self.assertEqual(unauthorized.status_code, 403)

        self.client.get("/logout")
        self._login("admin@klu.ac.in", "AdminPass123")
        with patch(
            "app.email_notifications.urlopen",
            return_value=self._accepted_response(),
        ) as send:
            approved = self.client.post(f"/admin/products/{product_id}/approve")
            repeated_approval = self.client.post(f"/admin/products/{product_id}/approve")
            rejected = self.client.post(f"/admin/products/{product_id}/reject")

        self.assertEqual(approved.status_code, 302)
        self.assertEqual(repeated_approval.status_code, 302)
        self.assertEqual(rejected.status_code, 302)
        self.assertEqual(send.call_count, 2)
        approval_request = send.call_args_list[0].args[0]
        approval_payload = json.loads(approval_request.data)
        self.assertEqual(approval_payload["to"], ["student@klu.ac.in"])
        self.assertIn("approved", approval_payload["subject"])
        self.assertIn("Moderated Textbook", approval_payload["text"])
        rejection_request = send.call_args_list[1].args[0]
        rejection_payload = json.loads(rejection_request.data)
        self.assertEqual(rejection_payload["to"], ["student@klu.ac.in"])
        self.assertIn("rejected", rejection_payload["subject"])
        self.assertIn("Moderated Textbook", rejection_payload["text"])
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Product, product_id).approval_status,
                "rejected",
            )

    def test_provider_failure_is_logged_without_undoing_approval_or_resending(self):
        with self.app.app_context():
            product = Product(
                seller_id=User.query.filter_by(role="student").one().id,
                category_id=self.category_id,
                title="Resend Failure Textbook",
                description="Description",
                price=Decimal("100.00"),
                listing_type="sale",
                condition="Good",
                location="Campus",
            )
            db.session.add(product)
            db.session.commit()
            product_id = product.id

        self._login("admin@klu.ac.in", "AdminPass123")
        with self.assertLogs("app", level="WARNING") as captured_logs:
            with patch(
                "app.email_notifications.urlopen",
                side_effect=URLError("temporary network failure"),
            ) as send:
                response = self.client.post(f"/admin/products/{product_id}/approve")
                repeated_response = self.client.post(f"/admin/products/{product_id}/approve")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(repeated_response.status_code, 302)
        send.assert_called_once()
        log_output = "\n".join(captured_logs.output)
        self.assertIn("Resend request failed", log_output)
        self.assertNotIn("re_test_key", log_output)
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Product, product_id).approval_status,
                "approved",
            )

    def test_network_failure_does_not_report_provider_acceptance(self):
        from app.email_notifications import notify_student_listing_moderated

        with self.app.test_request_context("/"):
            product = Product(
                seller_id=User.query.filter_by(role="student").one().id,
                category_id=self.category_id,
                title="Rejected Textbook",
                description="Description",
                price=Decimal("100.00"),
                listing_type="sale",
                condition="Good",
                location="Campus",
            )
            db.session.add(product)
            db.session.commit()

            with patch(
                "app.email_notifications.urlopen",
                side_effect=URLError("temporary network failure"),
            ):
                self.assertFalse(
                    notify_student_listing_moderated(product, "rejected")
                )

    def test_admin_moderation_still_requires_csrf_token(self):
        with self.app.app_context():
            product = Product(
                seller_id=User.query.filter_by(role="student").one().id,
                category_id=self.category_id,
                title="CSRF Textbook",
                description="Description",
                price=Decimal("100.00"),
                listing_type="sale",
                condition="Good",
                location="Campus",
            )
            db.session.add(product)
            db.session.commit()
            product_id = product.id

        self._login("admin@klu.ac.in", "AdminPass123")
        self.app.config["WTF_CSRF_ENABLED"] = True
        response = self.client.post(f"/admin/products/{product_id}/approve")

        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Product, product_id).approval_status,
                "pending",
            )


if __name__ == "__main__":
    unittest.main()
