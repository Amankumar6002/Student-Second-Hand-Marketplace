from datetime import datetime
from decimal import Decimal
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import (
    AdminProduct,
    GSTTransaction,
    Order,
    Payment,
    Product,
    User,
)

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")


def buyer_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_active:
            return render_template("error.html", code=403, message="Your account is suspended."), 403
        return view(*args, **kwargs)
    return wrapped


def generate_order_number():
    import random
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_suffix = str(random.randint(1000, 9999))
    return f"ORD-{timestamp}-{random_suffix}"


def calculate_order_totals(product_price, is_admin_store=False):
    product_price = Decimal(str(product_price))
    gst_rate = Decimal("0.18")
    platform_fee_rate = Decimal("0.05")

    gst_amount = product_price * gst_rate
    platform_fee = product_price * platform_fee_rate
    delivery_fee = Decimal("0")

    if is_admin_store:
        delivery_fee = Decimal("50")

    total_amount = product_price + gst_amount + platform_fee + delivery_fee
    return {
        "product_price": product_price,
        "gst_amount": gst_amount,
        "platform_fee": platform_fee,
        "delivery_fee": delivery_fee,
        "total_amount": total_amount,
    }


def get_payment_methods():
    return ["Cash on Delivery"]


@payments_bp.route("/checkout/<item_type>/<int:item_id>", methods=["GET", "POST"])
@buyer_required
def checkout(item_type, item_id):
    if item_type == "product":
        product = Product.query.get_or_404(item_id)
        if product.status != "available" or product.approval_status != "approved":
            flash("This product is no longer available.", "danger")
            return redirect(url_for("products.browse"))
        price = product.price
        is_admin_store = False
    elif item_type == "admin":
        product = AdminProduct.query.get_or_404(item_id)
        if product.status != "available" or product.stock <= 0:
            flash("This item is no longer available.", "danger")
            return redirect(url_for("admin_store.browse"))
        price = product.price
        is_admin_store = True
    else:
        flash("Invalid item type.", "error")
        return redirect(url_for("products.home"))

    totals = calculate_order_totals(price, is_admin_store)
    payment_methods = get_payment_methods()

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        if not payment_method:
            flash("Please select a payment method.", "danger")
            return render_template("payments/checkout.html", item=product, item_type=item_type, totals=totals, payment_methods=payment_methods)
        if payment_method not in payment_methods:
            flash("Please choose a valid payment method.", "danger")
            return render_template("payments/checkout.html", item=product, item_type=item_type, totals=totals, payment_methods=payment_methods)

        if product.status == "sold":
            flash("This product has already been sold.", "danger")
            return redirect(url_for("products.detail", product_id=product.id if item_type == "product" else item_id))

        existing_order = Order.query.filter_by(buyer_id=current_user.id, product_id=item_id if item_type == "product" else None, admin_product_id=item_id if item_type == "admin" else None).filter(
            Order.payment_status.in_(["pending", "created", "paid", "failed"]) 
        ).first()
        if existing_order and existing_order.payment_status in {"pending", "created", "failed"}:
            flash("You already have a purchase in progress for this item.", "info")
            return redirect(url_for("payments.checkout", item_type=item_type, item_id=item_id))
        if existing_order and existing_order.payment_status == "paid":
            flash("This item has already been purchased by your account.", "warning")
            return redirect(url_for("payments.success", order_id=existing_order.id))

        order_number = generate_order_number()
        if item_type == "admin":
            admin_user = User.query.filter_by(role="admin").first()
            seller_id = admin_user.id if admin_user else current_user.id
        else:
            seller_id = product.seller_id

        order = Order(
            order_number=order_number,
            buyer_id=current_user.id,
            seller_id=seller_id,
            product_id=item_id if item_type == "product" else None,
            admin_product_id=item_id if item_type == "admin" else None,
            order_type="admin_store" if is_admin_store else "student_marketplace",
            quantity=1,
            product_price=totals["product_price"],
            gst_amount=totals["gst_amount"],
            platform_fee=totals["platform_fee"],
            delivery_fee=totals["delivery_fee"],
            total_amount=totals["total_amount"],
            payment_method=payment_method,
            payment_status="pending",
            status="pending",
            currency="INR",
        )
        db.session.add(order)
        db.session.flush()

        if payment_method == "Cash on Delivery":
            order.payment_method = "Cash on Delivery"
            order.payment_status = "pending"
            order.status = "pending"
            db.session.add(order)
            db.session.commit()
            return redirect(url_for("payments.success", order_id=order.id))

    return render_template("payments/checkout.html", item=product, item_type=item_type, totals=totals, payment_methods=payment_methods)


@payments_bp.route("/payment/<int:order_id>", methods=["GET", "POST"])
@buyer_required
def payment_method(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("products.home"))

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        if payment_method == "Cash on Delivery":
            order.payment_method = "Cash on Delivery"
            order.payment_status = "pending"
            order.status = "pending"
            db.session.add(order)
            db.session.commit()
            return redirect(url_for("payments.success", order_id=order.id))
        flash("Unsupported payment method.", "danger")
        return redirect(url_for("payments.checkout", item_type="product" if order.product_id else "admin", item_id=order.product_id or order.admin_product_id))

    return render_template("payments/payment_method.html", order=order)


@payments_bp.route("/payment-form/<int:order_id>", methods=["GET", "POST"])
@buyer_required
def payment_form(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("products.home"))

    if request.method == "POST":
        flash("Select Cash on Delivery to complete your order.", "info")
        return redirect(url_for("payments.checkout", item_type="product" if order.product_id else "admin", item_id=order.product_id or order.admin_product_id))

    return render_template("payments/payment_form.html", order=order, payment_method=order.payment_method)


@payments_bp.route("/success/<int:order_id>")
@buyer_required
def success(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("products.home"))
    return render_template("payments/success.html", order=order)


@payments_bp.route("/my-orders")
@buyer_required
def my_orders():
    orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("payments/my_orders.html", orders=orders)


@payments_bp.route("/order/<int:order_id>")
@buyer_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("products.home"))
    payment = Payment.query.filter_by(order_id=order.id).first()
    gst_transaction = GSTTransaction.query.filter_by(order_id=order.id).first()
    return render_template("payments/order_detail.html", order=order, payment=payment, gst_transaction=gst_transaction)
