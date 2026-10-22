import unittest

from app import create_app
from app.extensions import db
from app.models import Category, Order, Product, User, ProductReview, UserReview


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()

            self.seller = User(
                name="Seller One",
                registration_number="20240001",
                university_email="seller1@klu.ac.in",
                department="CSE",
                section="A",
                phone="9999999999",
                role="student",
                is_verified=True,
            )
            self.seller.set_password("password123")

            self.buyer = User(
                name="Buyer One",
                registration_number="20240002",
                university_email="buyer1@klu.ac.in",
                department="ECE",
                section="B",
                phone="8888888888",
                role="student",
                is_verified=True,
            )
            self.buyer.set_password("password123")

            category = Category(name="Books", description="Books")
            db.session.add_all([self.seller, self.buyer, category])
            db.session.flush()

            self.product = Product(
                seller_id=self.seller.id,
                category_id=category.id,
                title="Chemistry Lab Manual",
                description="Used but in good condition.",
                price=450,
                listing_type="sale",
                condition="Good",
                location="Library",
                status="sold",
                approval_status="approved",
            )
            db.session.add(self.product)
            db.session.flush()

            self.order = Order(
                order_number="ORD-REVIEW-1",
                buyer_id=self.buyer.id,
                product_id=self.product.id,
                order_type="student_marketplace",
                quantity=1,
                product_price=450,
                gst_amount=81,
                platform_fee=22.5,
                delivery_fee=0,
                total_amount=553.5,
                payment_method="UPI",
                status="completed",
            )
            db.session.add(self.order)
            db.session.commit()

            self.product_id = self.product.id
            self.seller_id = self.seller.id
            self.buyer_id = self.buyer.id

    def login_as(self, user):
        user_id = user.id if hasattr(user, "id") else int(user)
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def test_product_review_requires_completed_transaction(self):
        self.login_as(self.buyer_id)
        response = self.client.post(
            f"/product/{self.product_id}/review",
            data={"rating": "5", "comment": "Nice book", "photo": ""},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(ProductReview.query.count(), 1)

    def test_duplicate_product_review_is_blocked(self):
        self.login_as(self.buyer_id)
        self.client.post(
            f"/product/{self.product_id}/review",
            data={"rating": "5", "comment": "Nice book"},
            follow_redirects=True,
        )
        response = self.client.post(
            f"/product/{self.product_id}/review",
            data={"rating": "4", "comment": "Second review"},
            follow_redirects=True,
        )
        self.assertIn(b"already reviewed", response.data.lower())

    def test_seller_review_is_recorded_for_completed_order(self):
        self.login_as(self.buyer_id)
        response = self.client.post(
            f"/user/{self.seller_id}/review",
            data={"rating": "5", "comment": "Fast delivery"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(UserReview.query.count(), 1)

    def test_invalid_rating_is_rejected(self):
        self.login_as(self.buyer_id)
        response = self.client.post(
            f"/product/{self.product_id}/review",
            data={"rating": "0", "comment": "Bad rating"},
            follow_redirects=True,
        )
        self.assertIn(b"between 1 and 5", response.data.lower())


if __name__ == "__main__":
    unittest.main()
