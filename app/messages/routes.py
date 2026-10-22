from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from ..auth.routes import active_required
from ..extensions import db
from ..models import Message, Product, User

messages_bp = Blueprint("messages", __name__)


@messages_bp.route("/messages")
@active_required
def inbox():
    messages = Message.query.filter(or_(Message.sender_id == current_user.id, Message.receiver_id == current_user.id)).order_by(Message.created_at.desc()).all()
    return render_template("messages/inbox.html", messages=messages)


@messages_bp.route("/messages/<int:user_id>", methods=["GET", "POST"])
@active_required
def conversation(user_id):
    other = User.query.get_or_404(user_id)
    if request.method == "POST":
        body = request.form.get("message", "").strip()
        product_id = request.form.get("product_id", type=int)
        if body:
            db.session.add(Message(sender_id=current_user.id, receiver_id=other.id, product_id=product_id, message=body))
            db.session.commit()
            flash("Message sent.", "success")
            return redirect(url_for("messages.conversation", user_id=other.id))
    history = Message.query.filter(or_((Message.sender_id == current_user.id) & (Message.receiver_id == other.id), (Message.sender_id == other.id) & (Message.receiver_id == current_user.id))).order_by(Message.created_at).all()
    return render_template("messages/conversation.html", other=other, messages=history, products=Product.query.filter_by(seller_id=current_user.id).all())
