from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.routes import active_required
from ..extensions import db
from ..models import Product, Rental

rentals_bp = Blueprint("rentals", __name__)


@rentals_bp.route("/rent/<int:product_id>", methods=["GET", "POST"])
@active_required
def rent(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        try:
            start = datetime.strptime(request.form["start_date"], "%Y-%m-%d").date()
            end = datetime.strptime(request.form["end_date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            flash("Choose valid rental dates.", "danger")
            return render_template("rentals/request.html", product=product)
        overlap = Rental.query.filter(Rental.product_id == product.id, Rental.status.in_(["pending", "approved", "active"]), Rental.start_date <= end, Rental.end_date >= start).first()
        if product.seller_id == current_user.id or product.listing_type not in {"rent", "both"} or start >= end or overlap:
            flash("Those dates are unavailable for this item.", "danger")
        else:
            days = (end - start).days
            db.session.add(Rental(product_id=product.id, renter_id=current_user.id, start_date=start, end_date=end, rental_price=product.rental_price * days))
            db.session.commit()
            flash("Rental request sent to the seller.", "success")
            return redirect(url_for("products.detail", product_id=product.id))
    return render_template("rentals/request.html", product=product)


@rentals_bp.route("/rentals")
@active_required
def history():
    rentals = Rental.query.filter_by(renter_id=current_user.id).order_by(Rental.created_at.desc()).all()
    return render_template("rentals/history.html", rentals=rentals)
