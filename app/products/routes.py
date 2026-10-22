import html
import os
import uuid
from decimal import Decimal
from io import BytesIO

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from ..auth.routes import active_required
from ..extensions import db
from ..models import (
    AdminProduct,
    Category,
    Order,
    Product,
    ProductImage,
    ProductReview,
    Report,
    ReviewReport,
    Transaction,
    User,
    UserReview,
    Wishlist,
)

products_bp = Blueprint("products", __name__)
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def admin_required(view):
    from functools import wraps
    @wraps(view)
    @active_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            return render_template("error.html", code=403, message="Admin access is required."), 403
        return view(*args, **kwargs)
    return wrapped


def sanitize_review_text(value):
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    return html.escape(cleaned, quote=False)


def build_rating_summary(reviews):
    distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for review in reviews:
        if review.rating in distribution:
            distribution[review.rating] += 1
    total = len(reviews)
    average = round(sum(review.rating for review in reviews) / total, 1) if total else 0.0
    return {
        "count": total,
        "average": average,
        "distribution": distribution,
    }


def get_completed_order_for_seller(buyer_id, seller_id):
    orders = Order.query.filter_by(buyer_id=buyer_id, status="completed").all()
    for order in orders:
        if order.seller_id == seller_id:
            return order
        if order.product_id:
            product = Product.query.get(order.product_id)
            if product and product.seller_id == seller_id:
                return order
    return None


def get_product_review_stats(product_id, admin_product_id=None):
    product_reviews = ProductReview.query.filter(
        (ProductReview.product_id == product_id) |
        (ProductReview.admin_product_id == (admin_product_id or product_id))
    ).order_by(ProductReview.created_at.desc()).all()
    return build_rating_summary(product_reviews)


def get_seller_review_stats(user_id):
    seller_reviews = UserReview.query.filter_by(seller_id=user_id).order_by(UserReview.created_at.desc()).all()
    return build_rating_summary(seller_reviews)


def _upload_review_image():
    image_file = request.files.get("photo")
    if not image_file or not image_file.filename:
        return None
    extension = image_file.filename.rsplit(".", 1)[-1].lower() if "." in image_file.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        flash("Review photos must be PNG, JPG, JPEG, or WEBP.", "danger")
        return False
    bytes_data = image_file.read()
    if len(bytes_data) > MAX_IMAGE_BYTES:
        flash("Review photo must be 5 MB or smaller.", "danger")
        return False
    try:
        with Image.open(BytesIO(bytes_data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError):
        flash("The uploaded review image is invalid.", "danger")
        return False
    filename = secure_filename(f"review_{uuid.uuid4().hex}.{extension}")
    target_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    with open(target_path, "wb") as file_handle:
        file_handle.write(bytes_data)
    return url_for("static", filename=f"uploads/{filename}")


@products_bp.route("/")
def home():
    featured = Product.query.filter_by(approval_status="approved", status="available").order_by(Product.created_at.desc()).limit(6).all()
    stats = {"students": 0, "listings": Product.query.filter_by(approval_status="approved").count(), "sold": Product.query.filter_by(status="sold").count(), "rented": 0}
    from ..models import Rental
    stats["students"] = User.query.count()
    stats["rented"] = Rental.query.filter_by(status="active").count()
    return render_template("index.html", featured=featured, stats=stats)


@products_bp.route("/products")
def browse():
    query = Product.query.filter_by(approval_status="approved")
    search = request.args.get("q", "").strip()
    if search:
        query = query.filter(Product.title.ilike(f"%{search}%") | Product.description.ilike(f"%{search}%"))
    if request.args.get("category"):
        query = query.join(Category).filter(Category.id == request.args["category"])
    if request.args.get("condition"):
        query = query.filter_by(condition=request.args["condition"])
    if request.args.get("listing_type"):
        query = query.filter(Product.listing_type.in_([request.args["listing_type"], "both"]))
    try:
        if request.args.get("min_price"): query = query.filter(Product.price >= Decimal(request.args["min_price"]))
        if request.args.get("max_price"): query = query.filter(Product.price <= Decimal(request.args["max_price"]))
    except Exception:
        flash("Please enter a valid price range.", "warning")
    sort = request.args.get("sort", "newest")
    query = query.order_by(Product.price.asc() if sort == "low" else Product.price.desc() if sort == "high" else Product.created_at.desc())
    products = query.paginate(page=request.args.get("page", 1, type=int), per_page=9, error_out=False)
    return render_template("products/browse.html", products=products, categories=Category.query.order_by(Category.name).all())


@products_bp.route("/product/<int:product_id>")
def detail(product_id):
    product = Product.query.get_or_404(product_id)
    if product.approval_status != "approved" and (not current_user.is_authenticated or (current_user.id != product.seller_id and current_user.role != "admin")):
        return render_template("error.html", code=404, message="That listing is not available."), 404
    reviews = ProductReview.query.filter_by(product_id=product.id).order_by(ProductReview.created_at.desc()).all()
    review_summary = build_rating_summary(reviews)
    seller_summary = get_seller_review_stats(product.seller_id)
    can_review_product = False
    if current_user.is_authenticated and current_user.id != product.seller_id:
        order = Order.query.filter_by(buyer_id=current_user.id, product_id=product.id, status="completed").first()
        can_review_product = bool(order) and not ProductReview.query.filter_by(order_id=order.id).first()
    return render_template(
        "products/detail.html",
        product=product,
        reviews=reviews,
        review_summary=review_summary,
        seller_summary=seller_summary,
        can_review_product=can_review_product,
    )


@products_bp.route("/product/<int:product_id>/review", methods=["POST"])
@active_required
def submit_product_review(product_id):
    product = Product.query.get_or_404(product_id)
    if current_user.id == product.seller_id:
        flash("You cannot review your own listing.", "danger")
        return redirect(url_for("products.detail", product_id=product.id))

    order = Order.query.filter_by(buyer_id=current_user.id, product_id=product.id, status="completed").first()
    if not order:
        flash("Only completed purchases or rentals can be reviewed.", "danger")
        return redirect(url_for("products.detail", product_id=product.id))
    if ProductReview.query.filter_by(order_id=order.id).first():
        flash("You have already reviewed this transaction.", "warning")
        return redirect(url_for("products.detail", product_id=product.id))

    rating_raw = request.form.get("rating", "").strip()
    try:
        rating = int(rating_raw)
    except (TypeError, ValueError):
        rating = 0
    if rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5.", "danger")
        return redirect(url_for("products.detail", product_id=product.id))

    comment = sanitize_review_text(request.form.get("comment", ""))
    if not comment:
        flash("Please add a review comment.", "danger")
        return redirect(url_for("products.detail", product_id=product.id))

    photo_url = _upload_review_image()
    if photo_url is False:
        return redirect(url_for("products.detail", product_id=product.id))

    review = ProductReview(
        product_id=product.id,
        user_id=current_user.id,
        order_id=order.id,
        rating=rating,
        comment=comment,
        image=photo_url,
    )
    db.session.add(review)
    db.session.commit()
    flash("Your review has been added.", "success")
    return redirect(url_for("products.detail", product_id=product.id))


@products_bp.route("/user/<int:user_id>")
def user_profile(user_id):
    seller = User.query.get_or_404(user_id)
    listings = Product.query.filter_by(seller_id=seller.id, approval_status="approved").order_by(Product.created_at.desc()).all()
    reviews = UserReview.query.filter_by(seller_id=seller.id).order_by(UserReview.created_at.desc()).all()
    review_summary = build_rating_summary(reviews)
    can_review_seller = False
    if current_user.is_authenticated and current_user.id != seller.id:
        order = get_completed_order_for_seller(current_user.id, seller.id)
        can_review_seller = bool(order) and not UserReview.query.filter_by(order_id=order.id).first()
    return render_template("user_profile.html", seller=seller, listings=listings, reviews=reviews, review_summary=review_summary, can_review_seller=can_review_seller)


@products_bp.route("/user/<int:user_id>/review", methods=["POST"])
@active_required
def submit_user_review(user_id):
    seller = User.query.get_or_404(user_id)
    if current_user.id == seller.id:
        flash("You cannot review yourself.", "danger")
        return redirect(url_for("products.user_profile", user_id=user_id))

    order = get_completed_order_for_seller(current_user.id, seller.id)
    if not order:
        flash("Only users who completed a transaction with this seller can submit a review.", "danger")
        return redirect(url_for("products.user_profile", user_id=user_id))
    if UserReview.query.filter_by(order_id=order.id).first():
        flash("You have already reviewed this seller for this transaction.", "warning")
        return redirect(url_for("products.user_profile", user_id=user_id))

    rating_raw = request.form.get("rating", "").strip()
    try:
        rating = int(rating_raw)
    except (TypeError, ValueError):
        rating = 0
    if rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5.", "danger")
        return redirect(url_for("products.user_profile", user_id=user_id))

    comment = sanitize_review_text(request.form.get("comment", ""))
    if not comment:
        flash("Please add a review comment.", "danger")
        return redirect(url_for("products.user_profile", user_id=user_id))

    review = UserReview(
        seller_id=seller.id,
        reviewer_id=current_user.id,
        order_id=order.id,
        rating=rating,
        comment=comment,
    )
    db.session.add(review)
    db.session.commit()
    flash("Seller review submitted.", "success")
    return redirect(url_for("products.user_profile", user_id=user_id))


@products_bp.route("/review/<string:review_type>/<int:review_id>/report", methods=["POST"])
@active_required
def report_review(review_type, review_id):
    if review_type not in {"product", "seller"}:
        flash("Invalid review type.", "danger")
        return redirect(request.referrer or url_for("products.home"))

    if review_type == "product":
        review = ProductReview.query.get_or_404(review_id)
    else:
        review = UserReview.query.get_or_404(review_id)

    reason = request.form.get("reason", "Other").strip()[:120] or "Other"
    description = sanitize_review_text(request.form.get("description", ""))
    existing = ReviewReport.query.filter_by(review_type=review_type, review_id=review.id, reporter_id=current_user.id).first()
    if existing:
        flash("You have already reported this review.", "warning")
        return redirect(request.referrer or url_for("products.home"))

    db.session.add(ReviewReport(review_type=review_type, review_id=review.id, reporter_id=current_user.id, reason=reason, description=description or None))
    db.session.commit()
    flash("The review has been reported to the admin team.", "success")
    return redirect(request.referrer or url_for("products.home"))


@products_bp.route("/profile")
@active_required
def profile():
    from ..models import Rental
    user_reviews = UserReview.query.filter_by(seller_id=current_user.id).order_by(UserReview.created_at.desc()).all()
    review_summary = build_rating_summary(user_reviews)
    return render_template(
        "profile.html",
        listings=Product.query.filter_by(seller_id=current_user.id).order_by(Product.created_at.desc()).all(),
        wishlist=Wishlist.query.filter_by(user_id=current_user.id).all(),
        rentals=Rental.query.filter_by(renter_id=current_user.id).order_by(Rental.created_at.desc()).all(),
        transactions=Transaction.query.filter_by(buyer_id=current_user.id).order_by(Transaction.created_at.desc()).all(),
        review_summary=review_summary,
        user_reviews=user_reviews,
    )


def _save_images(product):
    saved = 0
    for upload in request.files.getlist("images"):
        if not upload or not upload.filename or saved >= 6:
            continue
        extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
        if extension not in ALLOWED_EXTENSIONS:
            continue
        contents = upload.read()
        if len(contents) > MAX_IMAGE_BYTES:
            continue
        try:
            with Image.open(BytesIO(contents)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError):
            continue
        filename = secure_filename(f"{uuid.uuid4().hex}.{extension}")
        with open(os.path.join(current_app.config["UPLOAD_FOLDER"], filename), "wb") as image_file:
            image_file.write(contents)
        db.session.add(ProductImage(product_id=product.id, image_path=url_for("static", filename=f"uploads/{filename}")))
        saved += 1
    return saved


@products_bp.route("/product/create", methods=["GET", "POST"])
@active_required
def create():
    if not current_user.is_verified:
        flash("Your account must be verified before you can list an item.", "warning")
        return redirect(url_for("products.home"))
    categories = Category.query.order_by(Category.name).all()
    if request.method == "POST":
        # Extract and validate form data
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        listing_type = request.form.get("listing_type", "").strip()
        condition = request.form.get("condition", "").strip()
        location = request.form.get("location", "").strip()
        availability = request.form.get("availability", "").strip()
        
        # Validate required fields
        if not title:
            flash("Product name is required.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        if not description:
            flash("Description is required.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        if listing_type not in {"sale", "rent", "both"}:
            flash("Please select a valid listing type (Sell, Rent, or Both).", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        if not condition:
            flash("Please select a condition.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        if not location:
            flash("Pickup location is required.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        # Validate and convert category_id
        try:
            category_id = int(request.form.get("category_id", 0))
            if category_id <= 0:
                flash("Please select a category.", "danger")
                return render_template("products/form.html", categories=categories, product=None)
        except (ValueError, TypeError):
            flash("Please select a valid category.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        # Validate and convert price
        try:
            price = request.form.get("price", "").strip()
            if not price:
                flash("Price is required.", "danger")
                return render_template("products/form.html", categories=categories, product=None)
            price = Decimal(price)
            if price < 0:
                flash("Price cannot be negative.", "danger")
                return render_template("products/form.html", categories=categories, product=None)
        except (ValueError, TypeError, Exception):
            flash("Price must be a valid number.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        # Validate and convert rental_price if provided
        rental_price = None
        rental_price_str = request.form.get("rental_price", "").strip()
        if rental_price_str:
            try:
                rental_price = Decimal(rental_price_str)
                if rental_price < 0:
                    flash("Rental price cannot be negative.", "danger")
                    return render_template("products/form.html", categories=categories, product=None)
            except (ValueError, TypeError, Exception):
                flash("Rental price must be a valid number.", "danger")
                return render_template("products/form.html", categories=categories, product=None)
        
        # Create product with validated data
        product = Product(
            seller_id=current_user.id,
            category_id=category_id,
            title=title,
            description=description,
            price=price,
            rental_price=rental_price,
            listing_type=listing_type,
            condition=condition,
            location=location,
            availability=availability
        )
        
        try:
            db.session.add(product)
            db.session.flush()
            _save_images(product)
            db.session.commit()
            flash("Listing submitted for admin approval.", "success")
            return redirect(url_for("products.detail", product_id=product.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating listing: {str(e)}", "danger")
            return render_template("products/form.html", categories=categories, product=None)
    
    return render_template("products/form.html", categories=categories, product=None)


@products_bp.route("/product/<int:product_id>/edit", methods=["GET", "POST"])
@active_required
def edit(product_id):
    product = Product.query.get_or_404(product_id)
    if product.seller_id != current_user.id and current_user.role != "admin":
        return render_template("error.html", code=403, message="You can only edit your own listings."), 403
    categories = Category.query.order_by(Category.name).all()
    if request.method == "POST":
        # Extract and validate form data
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        listing_type = request.form.get("listing_type", "").strip()
        condition = request.form.get("condition", "").strip()
        location = request.form.get("location", "").strip()
        availability = request.form.get("availability", "").strip()
        
        # Validate required fields
        if not title:
            flash("Product name is required.", "danger")
            return render_template("products/edit.html", categories=categories, product=product)
        
        if not description:
            flash("Description is required.", "danger")
            return render_template("products/edit.html", categories=categories, product=product)
        
        if listing_type not in {"sale", "rent", "both"}:
            flash("Please select a valid listing type (Sell, Rent, or Both).", "danger")
            return render_template("products/edit.html", categories=categories, product=product)
        
        if not condition:
            flash("Please select a condition.", "danger")
            return render_template("products/edit.html", categories=categories, product=product)
        
        if not location:
            flash("Pickup location is required.", "danger")
            return render_template("products/edit.html", categories=categories, product=product)
        
        # Validate and convert category_id
        try:
            category_id = int(request.form.get("category_id", 0))
            if category_id <= 0:
                flash("Please select a category.", "danger")
                return render_template("products/edit.html", categories=categories, product=product)
        except (ValueError, TypeError):
            flash("Please select a valid category.", "danger")
            return render_template("products/edit.html", categories=categories, product=product)
        
        # Validate and convert price
        try:
            price = request.form.get("price", "").strip()
            if not price:
                flash("Price is required.", "danger")
                return render_template("products/edit.html", categories=categories, product=product)
            price = Decimal(price)
            if price < 0:
                flash("Price cannot be negative.", "danger")
                return render_template("products/edit.html", categories=categories, product=product)
        except (ValueError, TypeError, Exception):
            flash("Price must be a valid number.", "danger")
            return render_template("products/edit.html", categories=categories, product=product)
        
        # Validate and convert rental_price if provided
        rental_price = None
        rental_price_str = request.form.get("rental_price", "").strip()
        if rental_price_str:
            try:
                rental_price = Decimal(rental_price_str)
                if rental_price < 0:
                    flash("Rental price cannot be negative.", "danger")
                    return render_template("products/edit.html", categories=categories, product=product)
            except (ValueError, TypeError, Exception):
                flash("Rental price must be a valid number.", "danger")
                return render_template("products/edit.html", categories=categories, product=product)
        
        # Update product with validated data
        product.title = title
        product.description = description
        product.category_id = category_id
        product.condition = condition
        product.price = price
        product.rental_price = rental_price
        product.listing_type = listing_type
        product.location = location
        product.availability = availability
        
        try:
            _save_images(product)
            db.session.commit()
            flash("Listing updated.", "success")
            return redirect(url_for("products.detail", product_id=product.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating listing: {str(e)}", "danger")
            return render_template("products/edit.html", categories=categories, product=product)
    
    return render_template("products/edit.html", categories=categories, product=product)


@products_bp.route("/product/<int:product_id>/delete", methods=["POST"])
@active_required
def delete(product_id):
    product = Product.query.get_or_404(product_id)
    if product.seller_id != current_user.id and current_user.role != "admin":
        return render_template("error.html", code=403, message="You can only delete your own listings."), 403
    db.session.delete(product)
    db.session.commit()
    flash("Listing deleted.", "info")
    return redirect(url_for("products.my_listings"))


@products_bp.route("/product/<int:product_id>/status", methods=["POST"])
@active_required
def update_status(product_id):
    product = Product.query.get_or_404(product_id)
    if product.seller_id != current_user.id and current_user.role != "admin":
        return render_template("error.html", code=403, message="You can only update your own listings."), 403
    status = request.form.get("status")
    if status in {"available", "sold"}:
        product.status = status
        db.session.commit()
        flash(f"Listing marked as {status}.", "success")
    return redirect(url_for("products.my_listings"))


@products_bp.route("/my-listings")
@active_required
def my_listings():
    listings = Product.query.filter_by(seller_id=current_user.id).order_by(Product.created_at.desc()).all()
    return render_template("products/my_listings.html", listings=listings)


@products_bp.route("/wishlist/<int:product_id>", methods=["POST"])
@active_required
def wishlist(product_id):
    Product.query.get_or_404(product_id)
    saved = Wishlist.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if saved: db.session.delete(saved); flash("Removed from wishlist.", "info")
    else: db.session.add(Wishlist(user_id=current_user.id, product_id=product_id)); flash("Saved to wishlist.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("products.browse"))


@products_bp.route("/buy/<int:product_id>", methods=["POST"])
@active_required
def buy(product_id):
    product = Product.query.get_or_404(product_id)
    if product.seller_id == current_user.id or product.status != "available" or product.listing_type not in {"sale", "both"}:
        flash("This item is no longer available for purchase.", "danger")
        return redirect(url_for("products.detail", product_id=product.id))

    existing_order = Order.query.filter_by(buyer_id=current_user.id, product_id=product.id).filter(
        Order.payment_status.in_(["pending", "created", "paid"]) 
    ).first()
    if existing_order:
        flash("You already have a pending or completed order for this item.", "warning")
        return redirect(url_for("payments.checkout", item_type="product", item_id=product.id))

    db.session.add(
        Transaction(
            product_id=product.id,
            buyer_id=current_user.id,
            seller_id=product.seller_id,
            amount=product.price,
            status="requested",
        )
    )
    db.session.commit()
    return redirect(url_for("payments.checkout", item_type="product", item_id=product.id))


@products_bp.route("/report/<int:product_id>", methods=["POST"])
@active_required
def report(product_id):
    Product.query.get_or_404(product_id)
    db.session.add(Report(reporter_id=current_user.id, product_id=product_id, reason=request.form.get("reason", "Other"), description=request.form.get("description", "")))
    db.session.commit()
    flash("Thanks. Our moderation team will review this listing.", "success")
    return redirect(url_for("products.detail", product_id=product_id))


