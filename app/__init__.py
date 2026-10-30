import os

from authlib.integrations.flask_client import OAuth
from flask import Flask, current_app, render_template
from flask_login import current_user
from sqlalchemy import event

from config import Config
from .category_defaults import DEFAULT_CATEGORY_NAMES
from .extensions import csrf, db, login_manager, mail
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
    if "users" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        for column_name, column_sql in {
            "google_subject": "VARCHAR(255)",
            "google_picture_url": "VARCHAR(500)",
        }.items():
            if column_name not in user_columns:
                db.session.execute(
                    text(f"ALTER TABLE users ADD COLUMN {column_name} {column_sql}")
                )
        index_names = {index["name"] for index in inspector.get_indexes("users")}
        if "uq_users_google_subject" not in index_names:
            google_subject_index = next(
                index
                for index in User.__table__.indexes
                if index.name == "uq_users_google_subject"
            )
            google_subject_index.create(bind=db.engine, checkfirst=True)

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


def seed_default_categories():
    existing_names = {name for (name,) in db.session.query(Category.name).all()}
    missing_categories = [
        Category(name=name)
        for name in DEFAULT_CATEGORY_NAMES
        if name not in existing_names
    ]
    if missing_categories:
        db.session.add_all(missing_categories)
        db.session.commit()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    app_oauth = OAuth()
    app_oauth.init_app(app)
    mail.init_app(app)
    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        app_oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    else:
        missing_settings = [
            setting
            for setting in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
            if not app.config.get(setting)
        ]
        app.logger.warning(
            "Google sign-in is disabled; missing configuration: %s",
            ", ".join(missing_settings),
        )

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
        categories = Category.ordered()
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
        ensure_database_schema()
        db.create_all()
        ensure_database_schema()
        seed_default_categories()
        if not app.config.get("TESTING"):
            seed_default_admin()

    return app
