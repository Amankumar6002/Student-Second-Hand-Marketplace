# Kalasalingam Student Marketplace

A university-exclusive second-hand marketplace for Kalasalingam University students to discover, sell, rent, and discuss useful campus items.

## Included

- University-domain registration with hashed passwords, login/logout, CSRF protection, and role checks
- Google OpenID Connect sign-in for verified Kalasalingam University email addresses
- Approved listing marketplace with search, category, condition, price, listing-type filters, sorting, pagination, and responsive cards
- Secure multi-image uploads with extension validation and generated filenames
- Buy request workflow, rental requests with overlap prevention, wishlist, reports, direct messaging, and rental history
- Separate admin console for user verification/suspension, listing approval/rejection, reports, and categories
- Seed categories and an optional environment-configured admin account
- SQLite fallback for local development; PostgreSQL and MySQL URLs can be supplied through `DATABASE_URL`

## Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Local development uses `marketplace.db` by default. For PostgreSQL, set `DATABASE_URL` to the database URL supplied by your provider. Legacy Render URLs beginning with `postgres://` are normalized to `postgresql://`. Never commit production credentials.

Set `SECRET_KEY` to a long, random value and configure the university email domain. The default domain is `klu.ac.in`; adjust it if the university uses another configured domain.

For Google sign-in, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`. Configure the Google OAuth web client with the authorized origin `http://127.0.0.1:5000` and redirect URI `http://127.0.0.1:5000/login/google/callback`. Google-created accounts are regular student accounts and remain subject to the existing administrator verification process.

Email notifications are sent through the Resend HTTPS API. Configure `RESEND_API_KEY` and `RESEND_FROM` in the deployment environment (or local `.env`); when `RESEND_TEST_MODE=false`, `RESEND_FROM` must be an authorized production sender. To test without a domain, set `RESEND_TEST_MODE=true`. In this mode the application always uses Resend's documented `onboarding@resend.dev` sender and redirects all messages to the configured `RESEND_TEST_RECIPIENT` (default: `delivered@resend.dev`). For safety, the test recipient must be a valid address on Resend's `resend.dev` test domain, and email addresses in message bodies are redacted. Test mode confirms provider acceptance only, not inbox delivery. Turn test mode off for real notifications.

Set `ADMIN_NOTIFICATION_EMAIL` to the administrator inbox. If it is unset, production registration notifications to the administrator are skipped; Resend test mode still redirects them to the configured test recipient. `MAIL_USERNAME` is retained as a fallback support address; set `SUPPORT_EMAIL` for a separate support inbox. The legacy `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, and `MAIL_PASSWORD` settings are not used to send notifications.

Successful student registration sends a welcome email and an administrator verification notice. Admin verification sends a separate account-verification email; account verification remains distinct from activation and suspension. Notification failures are logged and do not roll back account changes. Set `PUBLIC_BASE_URL` to the canonical HTTPS application origin when deploying; it is used to generate marketplace links.

Run the app:

```powershell
python run.py
```

Visit `http://127.0.0.1:5000`.

## Development account

At startup, `admin@klu.ac.in` is created only when `DEFAULT_ADMIN_PASSWORD` is set and that account does not already exist. Existing accounts and passwords are left unchanged. Set the variable in `.env` for local development; do not use a committed or shared password. Students must register with a valid configured university email and are verified by an admin before publishing listings.

## Project structure

`app/__init__.py` creates the app and extensions. `app/models.py` contains normalized SQLAlchemy models. Auth, product, rental, messaging, and admin behavior live in Flask blueprints under `app/`. Templates and assets are in `app/templates` and `app/static`.

## Render and production notes

For the Render web service, set `DATABASE_URL` to the PostgreSQL **Internal Database URL** from the database dashboard. Also configure `SECRET_KEY`, `DEFAULT_ADMIN_PASSWORD`, and `PUBLIC_BASE_URL` (the canonical HTTPS service URL). If Google sign-in is enabled, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` and update the OAuth redirect URI to the production callback. For email, configure `RESEND_API_KEY`, `RESEND_FROM`, and `ADMIN_NOTIFICATION_EMAIL`; optionally set `SUPPORT_EMAIL` and `UNIVERSITY_EMAIL_DOMAIN`. Enter secrets in Render's environment settings, not in source files or chat.

Startup creates missing tables and contains compatibility additions for selected older columns; it is not a general schema migration system. `db.create_all()` does not migrate all changed model definitions. Use Flask-Migrate/Alembic for future schema changes, and take a verified database backup before migrations. No data is transferred from a local or deployed SQLite database by changing `DATABASE_URL`.

Render's local filesystem is not durable by default. Listing and store images are currently written under the app's local uploads directory, so they may disappear after a restart or redeploy. Keep the existing upload flow for now, but plan persistent object storage before relying on uploaded images in production; no storage provider is configured by this project.
