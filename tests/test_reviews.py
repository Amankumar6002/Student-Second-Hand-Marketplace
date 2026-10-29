import unittest
from datetime import datetime, timedelta
import re

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

    def add_product_reviews(self, ratings):
        with self.app.app_context():
            base_time = datetime(2026, 10, 1)
            for index, rating in enumerate(ratings):
                order = Order(
                    order_number=f"ORD-REVIEW-EXTRA-{index}",
                    buyer_id=self.buyer_id,
                    product_id=self.product_id,
                    order_type="student_marketplace",
                    quantity=1,
                    product_price=450,
                    gst_amount=81,
                    platform_fee=22.5,
                    delivery_fee=0,
                    total_amount=553.5,
                    payment_method="UPI",
                    status="completed",
                    created_at=base_time + timedelta(days=index),
                )
                db.session.add(order)
                db.session.flush()
                db.session.add(
                    ProductReview(
                        product_id=self.product_id,
                        user_id=self.buyer_id,
                        order_id=order.id,
                        rating=rating,
                        comment=f"Review {index}",
                        created_at=base_time + timedelta(days=index),
                    )
                )
            db.session.commit()

    def test_product_detail_empty_reviews_shows_real_zero_summary(self):
        response = self.client.get(f"/product/{self.product_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"0.0", response.data)
        self.assertIn(b"Be the first to review this product", response.data)
        self.assertIn(b'aria-valuenow="0"', response.data)
        self.assertNotIn(b'class="customer-review"', response.data)
        self.assertNotIn(b'id="write-review"', response.data)

    def test_one_review_has_actual_average_verified_status_and_distribution(self):
        self.add_product_reviews([4])
        response = self.client.get(f"/product/{self.product_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"4.0", response.data)
        self.assertIn(b"1 rating", response.data)
        self.assertIn(b"Verified purchase", response.data)
        self.assertIn(b'data-rating="4"', response.data)
        self.assertIn(b'aria-valuenow="100"', response.data)

    def test_many_reviews_support_summary_sort_filter_and_pagination(self):
        ratings = [1, 5, 3, 4, 2, 5, 1, 5, 4, 3, 2, 4]
        self.add_product_reviews(ratings)

        recent = self.client.get(f"/product/{self.product_id}")
        recent_ratings = re.findall(rb'data-rating="([1-5])"', recent.data)
        self.assertEqual(len(recent_ratings), 10)
        self.assertEqual(recent_ratings[0], b"4")
        self.assertIn(b"3.3", recent.data)
        self.assertIn(b"12 ratings and reviews", recent.data)
        self.assertIn(b'aria-valuenow="25"', recent.data)
        self.assertIn(b"Page 1 of 2", recent.data)

        highest = self.client.get(
            f"/product/{self.product_id}?sort=highest&page=1"
        )
        self.assertEqual(
            re.findall(rb'data-rating="([1-5])"', highest.data)[0],
            b"5",
        )

        lowest = self.client.get(
            f"/product/{self.product_id}?sort=lowest&page=1"
        )
        self.assertEqual(
            re.findall(rb'data-rating="([1-5])"', lowest.data)[0],
            b"1",
        )

        filtered = self.client.get(
            f"/product/{self.product_id}?rating=4&sort=highest"
        )
        filtered_ratings = re.findall(rb'data-rating="([1-5])"', filtered.data)
        self.assertEqual(filtered_ratings, [b"4", b"4", b"4"])
        self.assertIn(b"3 reviews", filtered.data)
        self.assertIn(b'value="4" selected', filtered.data)

    def test_guest_login_link_returns_to_product_and_eligible_buyer_sees_form(self):
        guest_page = self.client.get(f"/product/{self.product_id}")
        self.assertIn(
            f"/login?next=/product/{self.product_id}".encode(),
            guest_page.data,
        )

        self.login_as(self.buyer_id)
        eligible_page = self.client.get(f"/product/{self.product_id}")
        self.assertIn(b'id="write-review"', eligible_page.data)
        self.assertIn(b'name="rating"', eligible_page.data)
        self.assertIn(b"Submit review", eligible_page.data)

    def test_reporting_product_review_remains_available(self):
        self.add_product_reviews([5])
        with self.app.app_context():
            review_id = ProductReview.query.one().id
        self.login_as(self.buyer_id)

        response = self.client.post(
            f"/review/product/{review_id}/report",
            data={"reason": "Inappropriate", "description": "Test report"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"reported to the admin team", response.data)


if __name__ == "__main__":
    unittest.main()
