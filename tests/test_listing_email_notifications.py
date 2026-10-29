import smtplib
import unittest
from decimal import Decimal
from unittest.mock import patch

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

    def test_listing_is_committed_pending_before_admin_email(self):
        self._login("student@klu.ac.in", "StudentPass123")

        with patch("app.email_notifications.mail.send") as send:
            def assert_listing_was_committed(message):
                with self.app.app_context():
                    product = Product.query.one()
                    self.assertEqual(product.approval_status, "pending")

            send.side_effect = assert_listing_was_committed
            response = self._create_listing()

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        message = send.call_args.args[0]
        self.assertEqual(message.recipients, ["admin@example.com"])
        self.assertIn("Test Textbook", message.body)
        self.assertIn("250.00", message.body)
        self.assertIn("Books", message.body)
        self.assertIn("Test Student", message.body)
        self.assertIn("/admin/products", message.body)
        with self.app.app_context():
            product = Product.query.one()
            self.assertEqual(product.approval_status, "pending")
            self.assertEqual(product.title, "Test Textbook")

    def test_email_failure_keeps_one_pending_listing_and_refresh_does_not_resend(self):
        self._login("student@klu.ac.in", "StudentPass123")

        with self.assertLogs("app", level="WARNING") as captured_logs:
            with patch(
                "app.email_notifications.mail.send",
                side_effect=OSError("SMTP credentials must not be logged"),
            ) as send:
                response = self._create_listing()
                self.assertEqual(response.status_code, 302)
                self.client.get(response.headers["Location"])
                send.assert_called_once()
        self.assertNotIn("SMTP credentials must not be logged", "\n".join(captured_logs.output))

        with self.app.app_context():
            products = Product.query.all()
            self.assertEqual(len(products), 1)
            self.assertEqual(products[0].approval_status, "pending")

    def test_listing_edit_does_not_send_another_submission_notification(self):
        self._login("student@klu.ac.in", "StudentPass123")
        self._create_listing()
        with self.app.app_context():
            product_id = Product.query.one().id

        with patch("app.email_notifications.mail.send") as send:
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
        with patch("app.email_notifications.mail.send") as send:
            approved = self.client.post(f"/admin/products/{product_id}/approve")
            repeated_approval = self.client.post(f"/admin/products/{product_id}/approve")
            rejected = self.client.post(f"/admin/products/{product_id}/reject")

        self.assertEqual(approved.status_code, 302)
        self.assertEqual(repeated_approval.status_code, 302)
        self.assertEqual(rejected.status_code, 302)
        self.assertEqual(send.call_count, 2)
        approval_message = send.call_args_list[0].args[0]
        self.assertEqual(approval_message.recipients, ["student@klu.ac.in"])
        self.assertIn("approved", approval_message.subject)
        self.assertIn("Moderated Textbook", approval_message.body)
        rejection_message = send.call_args_list[1].args[0]
        self.assertEqual(rejection_message.recipients, ["student@klu.ac.in"])
        self.assertIn("rejected", rejection_message.subject)
        self.assertIn("Moderated Textbook", rejection_message.body)
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Product, product_id).approval_status,
                "rejected",
            )

    def test_smtp_disconnect_is_logged_without_undoing_approval_or_resending(self):
        with self.app.app_context():
            product = Product(
                seller_id=User.query.filter_by(role="student").one().id,
                category_id=self.category_id,
                title="SMTP Failure Textbook",
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
                "app.email_notifications.mail.send",
                side_effect=smtplib.SMTPServerDisconnected(),
            ) as send:
                response = self.client.post(f"/admin/products/{product_id}/approve")
                repeated_response = self.client.post(f"/admin/products/{product_id}/approve")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(repeated_response.status_code, 302)
        send.assert_called_once()
        log_output = "\n".join(captured_logs.output)
        self.assertIn("SMTP server disconnected", log_output)
        self.assertIn("Gmail App Password", log_output)
        self.assertNotIn("test-password", log_output)
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Product, product_id).approval_status,
                "approved",
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
