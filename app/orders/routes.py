from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Order, Product, AdminProduct, Payment, User

orders_bp = Blueprint("orders", __name__, url_prefix="/orders")


def buyer_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_active:
            return render_template("error.html", code=403, message="Your account is suspended."), 403
        return view(*args, **kwargs)
    return wrapped


def admin_only(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            return render_template("error.html", code=403, message="Admin access is required."), 403
        return view(*args, **kwargs)
    return wrapped


@orders_bp.route("/my-orders")
@buyer_required
def my_orders():
    """View all orders by current user"""
    page = request.args.get("page", 1, type=int)
    orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created_at.desc()).paginate(page=page, per_page=10)
    orders_end = min(orders.page * orders.per_page, orders.total)
    return render_template("orders/my_orders.html", orders=orders, orders_end=orders_end)


@orders_bp.route("/order/<int:order_id>")
@buyer_required
def order_detail(order_id):
    """View order details"""
    order = Order.query.get_or_404(order_id)
    
    if order.buyer_id != current_user.id:
        flash("Unauthorized access.", "error")
        return redirect(url_for("products.home"))
    
    payment = Payment.query.filter_by(order_id=order.id).first()
    
    if order.product_id:
        item = Product.query.get(order.product_id)
        item_type = "Student Marketplace"
    else:
        item = AdminProduct.query.get(order.admin_product_id)
        item_type = "KLU Store"
    
    return render_template("orders/order_detail.html", order=order, payment=payment, item=item, item_type=item_type)


@orders_bp.route("/admin/all-orders")
@admin_only
def admin_orders():
    """Admin view all orders"""
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status")
    
    query = Order.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    orders = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=15)
    return render_template("orders/admin_orders.html", orders=orders, status_filter=status_filter)


@orders_bp.route("/admin/order/<int:order_id>/update-status", methods=["POST"])
@admin_only
def update_order_status(order_id):
    """Update order status by admin"""
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status")
    
    if new_status not in ["pending", "paid", "delivered", "completed"]:
        flash("Invalid status.", "error")
        return redirect(request.referrer or url_for("orders.admin_orders"))
    
    order.status = new_status
    order.updated_at = datetime.utcnow()
    db.session.commit()
    
    flash(f"Order {order.order_number} status updated to {new_status}.", "success")
    return redirect(request.referrer or url_for("orders.admin_orders"))


@orders_bp.route("/admin/order/<int:order_id>")
@admin_only
def admin_order_detail(order_id):
    """Admin view order details"""
    order = Order.query.get_or_404(order_id)
    payment = Payment.query.filter_by(order_id=order.id).first()
    
    if order.product_id:
        item = Product.query.get(order.product_id)
        seller = User.query.get(item.seller_id)
        item_type = "Student Marketplace"
    else:
        item = AdminProduct.query.get(order.admin_product_id)
        seller = None
        item_type = "KLU Store"
    
    return render_template("orders/admin_order_detail.html", 
                         order=order, payment=payment, item=item, 
                         item_type=item_type, seller=seller)
