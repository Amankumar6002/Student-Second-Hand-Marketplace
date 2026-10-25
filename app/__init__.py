import os

from flask import Flask, current_app, render_template
from flask_login import current_user
from sqlalchemy import event

from config import Config
from .extensions import csrf, db, login_manager
from .models import Category, User


def seed_default_admin(*args, **kwargs):
    if current_app and current_app.config.get("TESTING"):
        return None

    admin = User.query.filter_by(university_email="admin@klu.ac.in").first()
    if admin:
        return admin

    admin = User(
        name="Marketplace Admin",
        registration_number="ADMIN-001",
        university_email="admin@klu.ac.in",
        department="Administration",
        section="A",
        role="admin",
        is_verified=True,
        is_active=True,
    )
    admin.set_password("ChangeMe123!")
    db.session.add(admin)
    db.session.commit()
    return admin


def ensure_database_schema():
    from sqlalchemy import text

    inspector = db.inspect(db.engine)
    if "orders" in inspector.get_table_names():
        order_columns = {column["name"] for column in inspector.get_columns("orders")}
        for column_name, column_sql in {
            "payment_status": "VARCHAR(30) DEFAULT 'pending' NOT NULL",
            "currency": "VARCHAR(10) DEFAULT 'INR' NOT NULL",
            "paid_at": "DATETIME",
        }.items():
            if column_name not in order_columns:
                db.session.execute(text(f"ALTER TABLE orders ADD COLUMN {column_name} {column_sql}"))

    if "payments" in inspector.get_table_names():
        payment_columns = {column["name"] for column in inspector.get_columns("payments")}
        for column_name, column_sql in {
            "payment_status": "VARCHAR(20) DEFAULT 'pending' NOT NULL",
            "currency": "VARCHAR(10) DEFAULT 'INR' NOT NULL",
            "paid_at": "DATETIME",
        }.items():
            if column_name not in payment_columns:
                db.session.execute(text(f"ALTER TABLE payments ADD COLUMN {column_name} {column_sql}"))

    db.session.commit()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth.routes import auth_bp
    from .products.routes import products_bp
    from .rentals.routes import rentals_bp
    from .messages.routes import messages_bp
    from .admin.routes import admin_bp
    from .payments.routes import payments_bp
    from .orders.routes import orders_bp
    from .admin_store.routes import admin_store_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(rentals_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(admin_store_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_globals():
        categories = Category.query.order_by(Category.name).all()
        return {"nav_categories": categories, "current_user": current_user}

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", code=400, message="That request could not be understood."), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("error.html", code=403, message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, message="We could not find that page."), 404

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return render_template("error.html", code=500, message="Something went wrong on our side."), 500

    event.listen(db.metadata, "after_create", seed_default_admin)

    with app.app_context():
        db.create_all()
        ensure_database_schema()
        if not app.config.get("TESTING"):
            seed_default_admin()

    return app
