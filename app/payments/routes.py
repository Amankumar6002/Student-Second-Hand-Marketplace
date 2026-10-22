import json
import logging
from datetime import datetime
from decimal import Decimal
from functools import wraps

import razorpay
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import (
    AdminEarnings,
    AdminProduct,
    GSTTransaction,
    Order,
    Payment,
    Product,
    User,
)

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")
logger = logging.getLogger(__name__)


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


def get_payment_methods(is_admin_store=False):
    methods = ["Razorpay"]
    if is_admin_store:
        methods.append("Cash on Delivery")
    return methods


def get_razorpay_client():
    key_id = current_app.config.get("RAZORPAY_KEY_ID")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        logger.warning(
            "Razorpay configuration missing: RAZORPAY_KEY_ID=%s, RAZORPAY_KEY_SECRET_present=%s",
            bool(key_id),
            bool(key_secret),
        )
        return None
    return razorpay.Client(auth=(key_id, key_secret))


def create_razorpay_order_for_local_order(order):
    client = get_razorpay_client()
    if client is None:
        raise RuntimeError("Razorpay credentials are not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in the environment.")

    total_amount = Decimal(str(order.total_amount))
    if total_amount <= 0:
        raise ValueError(f"Razorpay order amount must be positive. Order {order.id} total_amount={order.total_amount!r}")

    currency = current_app.config.get("RAZORPAY_CURRENCY", "INR")
    if currency.upper() != "INR":
        logger.warning("Razorpay order created with non-INR currency for order %s: %s", order.id, currency)

    amount_in_paise = int((total_amount * 100).quantize(Decimal("1")))
    payload = {
        "amount": amount_in_paise,
        "currency": currency,
        "receipt": order.order_number,
        "notes": {
            "order_id": order.id,
            "buyer_id": order.buyer_id,
            "seller_id": order.seller_id or "admin",
            "product_id": order.product_id or order.admin_product_id,
            "order_type": order.order_type,
        },
    }
    try:
        response = client.order.create(data=payload)
    except Exception:
        logger.exception("Razorpay order creation failed for order %s", order.id)
        raise

    order.razorpay_order_id = response.get("id")
    order.payment_status = "created"
    order.currency = payload["currency"]
    db.session.add(order)
    db.session.commit()
    return response


def resolve_product_for_order(order):
    if order.admin_product_id:
        return AdminProduct.query.get(order.admin_product_id), "admin"
    return Product.query.get(order.product_id), "product"


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
    payment_methods = get_payment_methods(is_admin_store)

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        if not payment_method:
            flash("Please select a payment method.", "danger")
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

        try:
            if payment_method == "Razorpay":
                create_razorpay_order_for_local_order(order)
                order.payment_method = "Razorpay"
                db.session.add(order)
                db.session.commit()
                return render_template(
                    "payments/checkout.html",
                    item=product,
                    item_type=item_type,
                    totals=totals,
                    payment_methods=payment_methods,
                    razorpay_key_id=current_app.config.get("RAZORPAY_KEY_ID"),
                    razorpay_order_id=order.razorpay_order_id,
                    razorpay_amount=int((Decimal(str(order.total_amount)) * 100).quantize(Decimal("1"))),
                    razorpay_currency=current_app.config.get("RAZORPAY_CURRENCY", "INR"),
                    order=order,
                    razorpay_ready=True,
                )

            if payment_method == "Cash on Delivery":
                order.payment_method = "Cash on Delivery"
                order.payment_status = "completed"
                order.status = "paid"
                order.paid_at = datetime.utcnow()
                db.session.add(order)
                db.session.commit()
                return redirect(url_for("payments.success", order_id=order.id))
        except Exception:
            db.session.rollback()
            logger.exception("Razorpay order creation failed for order %s", order.id)
            flash("We could not start the payment session right now. Please add valid Razorpay test credentials in the environment and try again later.", "danger")
            return render_template("payments/checkout.html", item=product, item_type=item_type, totals=totals, payment_methods=payment_methods)

        flash("Please choose a valid payment method.", "danger")
        return render_template("payments/checkout.html", item=product, item_type=item_type, totals=totals, payment_methods=payment_methods)

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
        if payment_method == "Razorpay":
            return redirect(url_for("payments.checkout", item_type="product" if order.product_id else "admin", item_id=order.product_id or order.admin_product_id))
        if payment_method == "Cash on Delivery":
            order.payment_method = "Cash on Delivery"
            order.payment_status = "completed"
            order.status = "paid"
            order.paid_at = datetime.utcnow()
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
        flash("This payment flow uses Razorpay checkout for secure online payments.", "info")
        return redirect(url_for("payments.checkout", item_type="product" if order.product_id else "admin", item_id=order.product_id or order.admin_product_id))

    return render_template("payments/payment_form.html", order=order, payment_method=order.payment_method)


@payments_bp.route("/verify", methods=["POST"])
@buyer_required
def verify_payment():
    payload = request.get_json(silent=True) or {}
    razorpay_payment_id = payload.get("razorpay_payment_id")
    razorpay_order_id = payload.get("razorpay_order_id")
    razorpay_signature = payload.get("razorpay_signature")
    order_id = payload.get("order_id")

    if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature, order_id]):
        return jsonify({"status": "error", "message": "Payment verification data is incomplete."}), 400

    order = Order.query.get(order_id)
    if not order:
        return jsonify({"status": "error", "message": "Order not found."}), 404
    if order.buyer_id != current_user.id:
        return jsonify({"status": "error", "message": "You are not allowed to verify this order."}), 403
    if order.razorpay_order_id != razorpay_order_id:
        return jsonify({"status": "error", "message": "Order mismatch while verifying payment."}), 400

    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET")
    if not key_secret:
        return jsonify({"status": "error", "message": "Razorpay is not configured in this environment."}), 500

    try:
        client = get_razorpay_client()
        if client is None:
            raise RuntimeError("Razorpay key configuration missing")
        params = {
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        }
        client.utility.verify_payment_signature(params)
    except Exception:
        logger.exception("Razorpay signature verification failed")
        order.payment_status = "failed"
        order.status = "pending"
        db.session.add(order)
        db.session.commit()
        return jsonify({"status": "error", "message": "Payment verification failed. Please try again."}), 400

    payment = Payment.query.filter_by(order_id=order.id).first()
    if payment is None:
        payment = Payment(
            order_id=order.id,
            user_id=order.buyer_id,
            amount=order.total_amount,
            payment_method="Razorpay",
            transaction_id=razorpay_payment_id,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            payment_status="completed",
            currency=order.currency or "INR",
            status="completed",
        )
        db.session.add(payment)
    else:
        payment.razorpay_order_id = razorpay_order_id
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_signature = razorpay_signature
        payment.payment_status = "completed"
        payment.status = "completed"
        payment.transaction_id = razorpay_payment_id
        payment.amount = order.total_amount
        payment.paid_at = datetime.utcnow()
        db.session.add(payment)

    order.payment_status = "paid"
    order.status = "paid"
    order.razorpay_payment_id = razorpay_payment_id
    order.paid_at = datetime.utcnow()
    db.session.add(order)

    product, product_type = resolve_product_for_order(order)
    if product is not None:
        if product_type == "admin":
            product.status = "unavailable"
            product.stock = max(0, product.stock - 1)
        else:
            product.status = "sold"
        db.session.add(product)

    gst_transaction = GSTTransaction.query.filter_by(order_id=order.id).first()
    if gst_transaction is None:
        gst_transaction = GSTTransaction(
            order_id=order.id,
            gst_amount=order.gst_amount,
            gst_rate=18.0,
            product_price=order.product_price,
        )
        db.session.add(gst_transaction)

    admin_earnings = AdminEarnings.query.filter_by(order_id=order.id).first()
    if admin_earnings is None:
        admin_earnings = AdminEarnings(
            order_id=order.id,
            platform_fee=order.platform_fee,
            gst_amount=order.gst_amount,
            total_earnings=order.platform_fee + order.gst_amount,
            transaction_type="purchase",
        )
        db.session.add(admin_earnings)

    db.session.commit()
    return jsonify({"status": "success", "redirect_url": url_for("payments.success", order_id=order.id)})


@payments_bp.route("/cancel/<int:order_id>")
@buyer_required
def payment_cancel(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("products.home"))

    order.payment_status = "failed"
    order.status = "pending"
    db.session.add(order)
    db.session.commit()
    flash("Payment was cancelled. The item remains available for purchase.", "warning")
    return redirect(url_for("payments.checkout", item_type="product" if order.product_id else "admin", item_id=order.product_id or order.admin_product_id))


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
