from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
from sqlalchemy import func, extract

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.routes import active_required
from ..email_notifications import (
    notify_account_suspended,
    notify_student_account_verified,
    notify_student_account_activated,
    notify_student_listing_moderated,
)
from ..extensions import db
from ..models import (
    Category, Product, Report, User, Order, Payment, GSTTransaction, 
    AdminEarnings, RentalCommission, Rental, AdminProduct, ProductReview, UserReview, ReviewReport
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_only(view):
    @wraps(view)
    @active_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            return render_template("error.html", code=403, message="Admin access is required."), 403
        return view(*args, **kwargs)
    return wrapped


def get_dashboard_stats():
    """Calculate all dashboard statistics"""
    total_users = User.query.count()
    verified_users = User.query.filter_by(is_verified=True).count()
    total_products = Product.query.count()
    pending_products = Product.query.filter_by(approval_status="pending").count()
    open_reports = Report.query.filter_by(status="open").count()
    
    # Orders statistics
    total_orders = Order.query.count()
    completed_orders = Order.query.filter_by(status="completed").count()
    pending_orders = Order.query.filter_by(status="pending").count()
    
    # Revenue statistics
    total_sales = db.session.query(func.sum(Order.product_price)).filter(Order.status.in_(["paid", "completed"])).scalar() or Decimal('0')
    total_gst = db.session.query(func.sum(GSTTransaction.gst_amount)).scalar() or Decimal('0')
    total_platform_fees = db.session.query(func.sum(AdminEarnings.platform_fee)).filter(AdminEarnings.transaction_type == "purchase").scalar() or Decimal('0')
    total_rental_commission = db.session.query(func.sum(RentalCommission.admin_commission)).filter(RentalCommission.status == "completed").scalar() or Decimal('0')
    
    total_admin_earnings = Decimal(str(total_gst)) + Decimal(str(total_platform_fees)) + Decimal(str(total_rental_commission))
    
    return {
        'users': total_users,
        'verified': verified_users,
        'products': total_products,
        'pending': pending_products,
        'reports': open_reports,
        'total_orders': total_orders,
        'completed_orders': completed_orders,
        'pending_orders': pending_orders,
        'total_sales': float(total_sales),
        'total_gst': float(total_gst),
        'total_platform_fees': float(total_platform_fees),
        'total_rental_commission': float(total_rental_commission),
        'total_admin_earnings': float(total_admin_earnings)
    }


@admin_bp.route("/")
@admin_only
def dashboard():
    stats = get_dashboard_stats()
    
    # Get recent orders
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    
    # Get monthly earnings data
    monthly_earnings = get_monthly_earnings()
    
    return render_template("admin/dashboard.html", stats=stats, recent_orders=recent_orders, monthly_earnings=monthly_earnings)


def get_monthly_earnings():
    """Get earnings data for last 12 months"""
    months = []
    for i in range(11, -1, -1):
        date = datetime.utcnow() - timedelta(days=30*i)
        year = date.year
        month = date.month
        month_name = date.strftime("%b %Y")
        
        # Calculate total earnings for the month
        gst = db.session.query(func.sum(GSTTransaction.gst_amount)).filter(
            extract('year', GSTTransaction.created_at) == year,
            extract('month', GSTTransaction.created_at) == month
        ).scalar() or Decimal('0')
        
        platform_fees = db.session.query(func.sum(AdminEarnings.platform_fee)).filter(
            extract('year', AdminEarnings.created_at) == year,
            extract('month', AdminEarnings.created_at) == month,
            AdminEarnings.transaction_type == "purchase"
        ).scalar() or Decimal('0')
        
        rental_commission = db.session.query(func.sum(RentalCommission.admin_commission)).filter(
            extract('year', RentalCommission.created_at) == year,
            extract('month', RentalCommission.created_at) == month,
            RentalCommission.status == "completed"
        ).scalar() or Decimal('0')
        
        total = float(Decimal(str(gst)) + Decimal(str(platform_fees)) + Decimal(str(rental_commission)))
        
        months.append({'name': month_name, 'total': total})
    
    return months


@admin_bp.route("/products")
@admin_only
def products():
    return render_template("admin/products.html", products=Product.query.order_by(Product.created_at.desc()).all())


@admin_bp.route("/products/<int:product_id>/<action>", methods=["POST"])
@admin_only
def moderate_product(product_id, action):
    product = Product.query.get_or_404(product_id)
    previous_approval_status = product.approval_status
    if action == "approve": product.approval_status = "approved"
    elif action == "reject": product.approval_status = "rejected"
    elif action == "remove": product.status = "unavailable"; product.approval_status = "rejected"
    else: return render_template("error.html", code=400, message="Unknown moderation action."), 400
    db.session.commit()
    if (
        product.approval_status != previous_approval_status
        and product.approval_status in {"approved", "rejected"}
    ):
        notify_student_listing_moderated(product, product.approval_status)
    flash("Listing moderation updated.", "success")
    return redirect(url_for("admin.products"))


@admin_bp.route("/users")
@admin_only
def users():
    return render_template("admin/users.html", users=User.query.order_by(User.created_at.desc()).all())


@admin_bp.route("/users/<int:user_id>/<action>", methods=["POST"])
@admin_only
def moderate_user(user_id, action):
    user = User.query.get_or_404(user_id)
    was_active = user.is_active
    was_verified = user.is_verified
    if action == "verify":
        user.is_verified = True
    elif action == "suspend":
        user.is_active = False
    elif action == "activate":
        user.is_active = True
    else:
        return render_template("error.html", code=400, message="Unknown user moderation action."), 400

    db.session.commit()
    if action == "suspend" and user.role == "student":
        flash("User suspended.", "success")
        if was_active and not notify_account_suspended(user):
            flash(
                "The suspension notification email could not be sent. Check the Resend configuration and server logs.",
                "warning",
            )
    elif action == "activate" and user.role == "student":
        flash("User activated.", "success")
        if not was_active and not notify_student_account_activated(user):
            flash(
                "The activation notification email could not be sent. Check the Resend configuration and server logs.",
                "warning",
            )
    elif action == "verify" and user.role == "student":
        flash("User verification updated.", "success")
        if not was_verified and not notify_student_account_verified(user):
            flash(
                "The verification notification email could not be sent. "
                "Check the Resend configuration and server logs.",
                "warning",
            )
    else:
        flash("User status updated.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/reports")
@admin_only
def reports():
    return render_template("admin/reports.html", reports=Report.query.order_by(Report.created_at.desc()).all())


@admin_bp.route("/reviews")
@admin_only
def reviews():
    product_reviews = ProductReview.query.order_by(ProductReview.created_at.desc()).all()
    user_reviews = UserReview.query.order_by(UserReview.created_at.desc()).all()
    reported_reviews = ReviewReport.query.order_by(ReviewReport.created_at.desc()).all()
    review_stats = {
        "product_reviews": len(product_reviews),
        "seller_reviews": len(user_reviews),
        "reported_reviews": len(reported_reviews),
        "product_avg": round(sum(r.rating for r in product_reviews) / len(product_reviews), 1) if product_reviews else 0,
        "seller_avg": round(sum(r.rating for r in user_reviews) / len(user_reviews), 1) if user_reviews else 0,
    }
    return render_template("admin/reviews.html", product_reviews=product_reviews, user_reviews=user_reviews, reported_reviews=reported_reviews, review_stats=review_stats)


@admin_bp.route("/reviews/<string:review_type>/<int:review_id>/remove", methods=["POST"])
@admin_only
def remove_review(review_type, review_id):
    if review_type == "product":
        review = ProductReview.query.get_or_404(review_id)
        db.session.delete(review)
    elif review_type == "seller":
        review = UserReview.query.get_or_404(review_id)
        db.session.delete(review)
    else:
        flash("Invalid review type.", "danger")
        return redirect(request.referrer or url_for("admin.reviews"))
    db.session.commit(); flash("Review removed by moderator.", "success")
    return redirect(request.referrer or url_for("admin.reviews"))


@admin_bp.route("/reviews/reported")
@admin_only
def reported_reviews():
    reported = ReviewReport.query.order_by(ReviewReport.created_at.desc()).all()
    return render_template("admin/reviews.html", product_reviews=[], user_reviews=[], reported_reviews=reported, review_stats={})


@admin_bp.route("/categories", methods=["GET", "POST"])
@admin_only
def categories():
    if request.method == "POST" and request.form.get("name"):
        db.session.add(Category(name=request.form["name"].strip(), description=request.form.get("description", "").strip()))
        db.session.commit(); flash("Category added.", "success")
    return render_template("admin/categories.html", categories=Category.query.order_by(Category.name).all())


@admin_bp.route("/earnings")
@admin_only
def earnings():
    """View detailed earnings breakdown"""
    page = request.args.get("page", 1, type=int)
    earnings_records = AdminEarnings.query.order_by(AdminEarnings.created_at.desc()).paginate(page=page, per_page=20)
    
    # Calculate totals
    total_earnings = db.session.query(func.sum(AdminEarnings.total_earnings)).scalar() or Decimal('0')
    platform_fees_total = db.session.query(func.sum(AdminEarnings.platform_fee)).scalar() or Decimal('0')
    gst_total = db.session.query(func.sum(AdminEarnings.gst_amount)).scalar() or Decimal('0')
    
    stats = {
        'total_earnings': float(total_earnings),
        'platform_fees': float(platform_fees_total),
        'gst': float(gst_total),
        'record_count': AdminEarnings.query.count()
    }
    
    return render_template("admin/earnings.html", earnings=earnings_records, stats=stats)


@admin_bp.route("/gst-report")
@admin_only
def gst_report():
    """View GST collection report"""
    page = request.args.get("page", 1, type=int)
    gst_records = GSTTransaction.query.order_by(GSTTransaction.created_at.desc()).paginate(page=page, per_page=20)
    
    # Calculate GST statistics
    total_gst = db.session.query(func.sum(GSTTransaction.gst_amount)).scalar() or Decimal('0')
    total_taxable_value = db.session.query(func.sum(GSTTransaction.product_price)).scalar() or Decimal('0')
    gst_transactions_count = GSTTransaction.query.count()
    
    stats = {
        'total_gst': float(total_gst),
        'total_taxable_value': float(total_taxable_value),
        'gst_rate': 18.0,
        'transaction_count': gst_transactions_count
    }
    
    return render_template("admin/gst_report.html", gst_records=gst_records, stats=stats)


@admin_bp.route("/rental-commissions")
@admin_only
def rental_commissions():
    """View rental commission details"""
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status")
    
    query = RentalCommission.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    commissions = query.order_by(RentalCommission.created_at.desc()).paginate(page=page, per_page=20)
    
    # Calculate totals
    total_rental_amount = db.session.query(func.sum(RentalCommission.rental_amount)).scalar() or Decimal('0')
    admin_commission_total = db.session.query(func.sum(RentalCommission.admin_commission)).scalar() or Decimal('0')
    seller_amount_total = db.session.query(func.sum(RentalCommission.seller_amount)).scalar() or Decimal('0')
    pending_commission = db.session.query(func.sum(RentalCommission.admin_commission)).filter_by(status="pending").scalar() or Decimal('0')
    completed_commission = db.session.query(func.sum(RentalCommission.admin_commission)).filter_by(status="completed").scalar() or Decimal('0')
    
    stats = {
        'total_rental_amount': float(total_rental_amount),
        'admin_commission_total': float(admin_commission_total),
        'seller_amount_total': float(seller_amount_total),
        'pending': float(pending_commission),
        'completed': float(completed_commission),
        'commission_rate': 10.0
    }
    
    return render_template("admin/rental_commissions.html", commissions=commissions, stats=stats, status_filter=status_filter)


@admin_bp.route("/rental-commissions/<int:commission_id>/update-status", methods=["POST"])
@admin_only
def update_commission_status(commission_id):
    """Update rental commission status"""
    commission = RentalCommission.query.get_or_404(commission_id)
    new_status = request.form.get("status")
    
    if new_status in ["pending", "completed"]:
        commission.status = new_status
        db.session.commit()
        flash(f"Commission status updated to {new_status}.", "success")
    else:
        flash("Invalid status.", "error")
    
    return redirect(request.referrer or url_for("admin.rental_commissions"))


@admin_bp.route("/settings")
@admin_only
def settings():
    """Admin settings page"""
    return render_template("admin/settings.html")
