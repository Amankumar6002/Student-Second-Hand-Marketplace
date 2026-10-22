import os
from datetime import datetime
from decimal import Decimal
from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import AdminProduct, Order, ProductReview

admin_store_bp = Blueprint("admin_store", __name__, url_prefix="/klu-store")


def admin_only(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            return render_template("error.html", code=403, message="Admin access is required."), 403
        return view(*args, **kwargs)
    return wrapped


def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@admin_store_bp.route("/")
def browse():
    """Browse KLU Store products"""
    page = request.args.get("page", 1, type=int)
    category = request.args.get("category")
    search = request.args.get("search")
    
    query = AdminProduct.query.filter_by(status="available")
    
    if category:
        query = query.filter_by(category=category)
    
    if search:
        query = query.filter(
            (AdminProduct.title.ilike(f"%{search}%")) |
            (AdminProduct.description.ilike(f"%{search}%"))
        )
    
    products = query.order_by(AdminProduct.created_at.desc()).paginate(page=page, per_page=12)
    
    # Get all categories
    categories = db.session.query(AdminProduct.category).distinct().order_by(AdminProduct.category).all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    return render_template("admin_store/browse.html", products=products, categories=categories, current_category=category, search=search)


def build_rating_summary(reviews):
    distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for review in reviews:
        if review.rating in distribution:
            distribution[review.rating] += 1
    total = len(reviews)
    average = round(sum(review.rating for review in reviews) / total, 1) if total else 0.0
    return {"count": total, "average": average, "distribution": distribution}


@admin_store_bp.route("/product/<int:product_id>")
def detail(product_id):
    """View product details"""
    product = AdminProduct.query.get_or_404(product_id)
    
    if product.status != "available" or product.stock <= 0:
        flash("This product is no longer available.", "error")
        return redirect(url_for("admin_store.browse"))

    reviews = ProductReview.query.filter_by(admin_product_id=product.id).order_by(ProductReview.created_at.desc()).all()
    review_summary = build_rating_summary(reviews)
    can_review_product = False
    if current_user.is_authenticated:
        order = Order.query.filter_by(buyer_id=current_user.id, admin_product_id=product.id, status="completed").first()
        can_review_product = bool(order) and not ProductReview.query.filter_by(order_id=order.id).first()

    return render_template("admin_store/detail.html", product=product, reviews=reviews, review_summary=review_summary, can_review_product=can_review_product)


@admin_store_bp.route("/product/<int:product_id>/review", methods=["POST"])
@login_required
def submit_product_review(product_id):
    product = AdminProduct.query.get_or_404(product_id)

    order = Order.query.filter_by(buyer_id=current_user.id, admin_product_id=product.id, status="completed").first()
    if not order:
        flash("Only completed KLU Store purchases can be reviewed.", "danger")
        return redirect(url_for("admin_store.detail", product_id=product.id))
    if ProductReview.query.filter_by(order_id=order.id).first():
        flash("You have already reviewed this KLU Store order.", "warning")
        return redirect(url_for("admin_store.detail", product_id=product.id))

    rating_raw = request.form.get("rating", "").strip()
    try:
        rating = int(rating_raw)
    except (TypeError, ValueError):
        rating = 0
    if rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5.", "danger")
        return redirect(url_for("admin_store.detail", product_id=product.id))

    comment = request.form.get("comment", "").strip()
    if not comment:
        flash("Please add a review comment.", "danger")
        return redirect(url_for("admin_store.detail", product_id=product.id))

    photo_url = None
    if "photo" in request.files and request.files["photo"].filename:
        file = request.files["photo"]
        allowed = {"png", "jpg", "jpeg", "webp"}
        extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if extension not in allowed:
            flash("Review photos must be PNG, JPG, JPEG, or WEBP.", "danger")
            return redirect(url_for("admin_store.detail", product_id=product.id))
        filename = f"review_{current_user.id}_{product.id}_{int(__import__('time').time())}.{extension}"
        file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
        photo_url = url_for("static", filename=f"uploads/{filename}")

    db.session.add(ProductReview(
        product_id=None,
        admin_product_id=product.id,
        user_id=current_user.id,
        order_id=order.id,
        rating=rating,
        comment=comment,
        image=photo_url,
    ))
    db.session.commit()
    flash("Your KLU Store review has been added.", "success")
    return redirect(url_for("admin_store.detail", product_id=product.id))


@admin_store_bp.route("/admin/manage")
@admin_only
def manage():
    """Manage KLU Store products (Admin)"""
    page = request.args.get("page", 1, type=int)
    products = AdminProduct.query.order_by(AdminProduct.created_at.desc()).paginate(page=page, per_page=20)
    return render_template("admin_store/manage.html", products=products)


@admin_store_bp.route("/admin/add", methods=["GET", "POST"])
@admin_only
def add_product():
    """Add new product to KLU Store"""
    if request.method == "POST":
        os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
        title = request.form.get("title")
        description = request.form.get("description")
        price = request.form.get("price")
        stock = request.form.get("stock")
        category = request.form.get("category")
        
        if not all([title, description, price, stock, category]):
            flash("All fields are required.", "error")
            return render_template("admin_store/add_product.html")
        
        try:
            price = Decimal(str(price))
            stock = int(stock)
        except (ValueError, TypeError):
            flash("Invalid price or stock value.", "error")
            return render_template("admin_store/add_product.html")
        
        if price <= 0 or stock < 0:
            flash("Price must be positive and stock cannot be negative.", "error")
            return render_template("admin_store/add_product.html")
        
        image_path = None
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filename = f"admin_{datetime.utcnow().timestamp()}_{filename}"
                file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                image_path = f"uploads/{filename}"
        
        product = AdminProduct(
            title=title,
            description=description,
            price=price,
            stock=stock,
            category=category,
            image_path=image_path,
            status="available"
        )
        db.session.add(product)
        db.session.commit()
        
        flash(f"Product '{title}' added successfully.", "success")
        return redirect(url_for("admin_store.manage"))
    
    return render_template("admin_store/add_product.html")


@admin_store_bp.route("/admin/edit/<int:product_id>", methods=["GET", "POST"])
@admin_only
def edit_product(product_id):
    """Edit KLU Store product"""
    product = AdminProduct.query.get_or_404(product_id)
    
    if request.method == "POST":
        product.title = request.form.get("title") or product.title
        product.description = request.form.get("description") or product.description
        
        price = request.form.get("price")
        stock = request.form.get("stock")
        
        if price:
            try:
                product.price = Decimal(str(price))
            except (ValueError, TypeError):
                flash("Invalid price value.", "error")
                return render_template("admin_store/edit_product.html", product=product)
        
        if stock:
            try:
                product.stock = int(stock)
            except ValueError:
                flash("Invalid stock value.", "error")
                return render_template("admin_store/edit_product.html", product=product)
        
        product.category = request.form.get("category") or product.category
        product.updated_at = datetime.utcnow()
        
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename):
                # Delete old image if exists
                if product.image_path:
                    old_path = os.path.join(current_app.config["UPLOAD_FOLDER"], product.image_path.replace("uploads/", ""))
                    if os.path.exists(old_path):
                        os.remove(old_path)
                
                filename = secure_filename(file.filename)
                filename = f"admin_{datetime.utcnow().timestamp()}_{filename}"
                file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                product.image_path = f"uploads/{filename}"
        
        db.session.commit()
        flash(f"Product '{product.title}' updated successfully.", "success")
        return redirect(url_for("admin_store.manage"))
    
    return render_template("admin_store/edit_product.html", product=product)


@admin_store_bp.route("/admin/delete/<int:product_id>", methods=["POST"])
@admin_only
def delete_product(product_id):
    """Delete KLU Store product"""
    product = AdminProduct.query.get_or_404(product_id)
    product_title = product.title
    
    # Delete image if exists
    if product.image_path:
        image_path = os.path.join(current_app.config["UPLOAD_FOLDER"], product.image_path.replace("uploads/", ""))
        if os.path.exists(image_path):
            os.remove(image_path)
    
    db.session.delete(product)
    db.session.commit()
    
    flash(f"Product '{product_title}' deleted successfully.", "success")
    return redirect(url_for("admin_store.manage"))
