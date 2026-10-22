import unittest

from app import create_app
from app.extensions import db
from app.models import Category, Order, Product, User


class MyOrdersPageTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()

            buyer = User(
                name='Buyer User',
                registration_number='BUY-100',
                university_email='buyer@klu.ac.in',
                department='CSE',
                section='A',
                phone='9876543210',
                role='student',
                is_verified=True,
                is_active=True,
            )
            buyer.set_password('StrongPass123')

            seller = User(
                name='Seller User',
                registration_number='SELL-100',
                university_email='seller@klu.ac.in',
                department='MECH',
                section='B',
                phone='9988776655',
                role='student',
                is_verified=True,
                is_active=True,
            )
            seller.set_password('StrongPass123')

            category = Category(name='Electronics', description='Sample category')
            db.session.add_all([buyer, seller, category])
            db.session.commit()

            product = Product(
                seller_id=seller.id,
                category_id=category.id,
                title='Used Laptop',
                description='Working condition laptop',
                price=25000,
                rental_price=None,
                listing_type='sale',
                condition='Good',
                location='Hostel',
                availability='Available',
                status='available',
                approval_status='approved',
            )
            db.session.add(product)
            db.session.commit()

            order = Order(
                order_number='ORD-TEST-001',
                buyer_id=buyer.id,
                seller_id=seller.id,
                product_id=product.id,
                order_type='student_marketplace',
                quantity=1,
                product_price=25000,
                gst_amount=4500,
                platform_fee=1250,
                delivery_fee=0,
                total_amount=30750,
                payment_method='Cash on Delivery',
                payment_status='completed',
                status='paid',
                currency='INR',
            )
            db.session.add(order)
            db.session.commit()

            self.buyer_email = buyer.university_email
            self.buyer_password = 'StrongPass123'

    def test_my_orders_page_renders_for_cod_orders(self):
        login_response = self.client.post(
            '/login',
            data={'email': self.buyer_email, 'password': self.buyer_password},
            follow_redirects=True,
        )
        self.assertEqual(login_response.status_code, 200)

        response = self.client.get('/orders/my-orders')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'My Orders', response.data)
        self.assertIn(b'Cash on Delivery', response.data)
        self.assertIn(b'Order #', response.data)
        self.assertIn(b'Showing 1 - 1 of 1 orders', response.data)


if __name__ == '__main__':
    unittest.main()
