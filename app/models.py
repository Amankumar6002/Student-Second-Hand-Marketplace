from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    registration_number = db.Column(db.String(40), unique=True, nullable=False)
    university_email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    department = db.Column(db.String(120), nullable=False)
    section = db.Column(db.String(20), nullable=False)
    phone = db.Column(db.String(20))
    profile_image = db.Column(db.String(255))
    role = db.Column(db.String(20), default="student", nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    products = db.relationship("Product", back_populates="seller", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    products = db.relationship("Product", back_populates="category")


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(10, 2), default=0)
    rental_price = db.Column(db.Numeric(10, 2))
    listing_type = db.Column(db.String(20), nullable=False)
    condition = db.Column(db.String(30), nullable=False)
    location = db.Column(db.String(120), nullable=False)
    availability = db.Column(db.String(160))
    status = db.Column(db.String(30), default="available", nullable=False)
    approval_status = db.Column(db.String(30), default="pending", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    seller = db.relationship("User", back_populates="products")
    category = db.relationship("Category", back_populates="products")
    images = db.relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    rentals = db.relationship("Rental", back_populates="product")
    transactions = db.relationship("Transaction", back_populates="product")
    reports = db.relationship("Report", back_populates="product")

    @property
    def image_url(self):
        return self.images[0].image_path if self.images else "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=800&q=80"


class ProductReview(db.Model):
    __tablename__ = "product_reviews"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=True)
    admin_product_id = db.Column(db.Integer, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, unique=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewer = db.relationship("User", foreign_keys=[user_id])
    order = db.relationship("Order", foreign_keys=[order_id])


class UserReview(db.Model):
    __tablename__ = "user_reviews"
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, unique=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    seller = db.relationship("User", foreign_keys=[seller_id])
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])
    order = db.relationship("Order", foreign_keys=[order_id])


class ReviewReport(db.Model):
    __tablename__ = "review_reports"
    id = db.Column(db.Integer, primary_key=True)
    review_type = db.Column(db.String(20), nullable=False)
    review_id = db.Column(db.Integer, nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reporter = db.relationship("User", foreign_keys=[reporter_id])


class ProductImage(db.Model):
    __tablename__ = "product_images"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship("Product", back_populates="images")


class Rental(db.Model):
    __tablename__ = "rentals"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    renter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    rental_price = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)
    return_status = db.Column(db.String(20), default="not_returned")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship("Product", back_populates="rentals")
    renter = db.relationship("User")


class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    transaction_type = db.Column(db.String(20), default="purchase")
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default="requested")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship("Product", back_populates="transactions")
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])


class Wishlist(db.Model):
    __tablename__ = "wishlist"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("user_id", "product_id"),)


class Report(db.Model):
    __tablename__ = "reports"
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    reason = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship("Product", back_populates="reports")
    reporter = db.relationship("User")


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])
    product = db.relationship("Product")


class AdminProduct(db.Model):
    """Official KLU Store products managed only by Admin"""
    __tablename__ = "admin_products"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, default=0, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    image_path = db.Column(db.String(255))
    status = db.Column(db.String(30), default="available", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    orders = db.relationship("Order", back_populates="admin_product")

    @property
    def image_url(self):
        default_url = "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=800&q=80"
        if not self.image_path:
            return default_url

        value = self.image_path.strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if value.startswith("/static/"):
            return value
        if value.startswith("uploads/"):
            try:
                from flask import current_app, url_for
                if current_app and current_app.url_map is not None:
                    return url_for("static", filename=value)
            except Exception:
                pass
            return "/static/" + value
        if value.startswith("/"):
            return value
        try:
            from flask import current_app, url_for
            if current_app and current_app.url_map is not None:
                return url_for("static", filename=f"uploads/{value}")
        except Exception:
            pass
        return "/static/uploads/" + value


class Order(db.Model):
    """Orders for both student marketplace and admin store"""
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    admin_product_id = db.Column(db.Integer, db.ForeignKey("admin_products.id"))
    order_type = db.Column(db.String(20), nullable=False)  # 'student_marketplace' or 'admin_store'
    quantity = db.Column(db.Integer, default=1, nullable=False)
    product_price = db.Column(db.Numeric(10, 2), nullable=False)
    gst_amount = db.Column(db.Numeric(10, 2), default=0)
    platform_fee = db.Column(db.Numeric(10, 2), default=0)
    delivery_fee = db.Column(db.Numeric(10, 2), default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    payment_status = db.Column(db.String(30), default="pending", nullable=False)
    razorpay_order_id = db.Column(db.String(120), nullable=True)
    razorpay_payment_id = db.Column(db.String(120), nullable=True)
    currency = db.Column(db.String(10), default="INR", nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(30), default="pending", nullable=False)  # pending, paid, delivered, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])
    product = db.relationship("Product", foreign_keys=[product_id])
    admin_product = db.relationship("AdminProduct", back_populates="orders")
    payments = db.relationship("Payment", back_populates="order")


class Payment(db.Model):
    """Payment records for all transactions"""
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)  # UPI, Debit Card, Credit Card, Net Banking, Cash on Delivery
    transaction_id = db.Column(db.String(100), unique=True)
    razorpay_order_id = db.Column(db.String(120), nullable=True)
    razorpay_payment_id = db.Column(db.String(120), nullable=True)
    razorpay_signature = db.Column(db.String(255), nullable=True)
    payment_status = db.Column(db.String(20), default="pending", nullable=False)  # pending, completed, failed
    currency = db.Column(db.String(10), default="INR", nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending, completed, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    order = db.relationship("Order", back_populates="payments")
    user = db.relationship("User", foreign_keys=[user_id])


class GSTTransaction(db.Model):
    """Track GST collected from transactions"""
    __tablename__ = "gst_transactions"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    gst_amount = db.Column(db.Numeric(10, 2), nullable=False)
    gst_rate = db.Column(db.Float, default=18.0)  # 18% GST
    product_price = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AdminEarnings(db.Model):
    """Track admin earnings from platform fees and GST"""
    __tablename__ = "admin_earnings"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    platform_fee = db.Column(db.Numeric(10, 2), default=0)
    gst_amount = db.Column(db.Numeric(10, 2), default=0)
    rental_commission = db.Column(db.Numeric(10, 2), default=0)
    total_earnings = db.Column(db.Numeric(10, 2), default=0)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'purchase', 'rental'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class RentalCommission(db.Model):
    """Track rental commissions - 10% to admin, 90% to seller"""
    __tablename__ = "rental_commissions"
    id = db.Column(db.Integer, primary_key=True)
    rental_id = db.Column(db.Integer, db.ForeignKey("rentals.id"), nullable=False)
    rental_amount = db.Column(db.Numeric(10, 2), nullable=False)
    admin_commission = db.Column(db.Numeric(10, 2), nullable=False)  # 10% of rental_amount
    seller_amount = db.Column(db.Numeric(10, 2), nullable=False)  # 90% of rental_amount
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    rental = db.relationship("Rental")
