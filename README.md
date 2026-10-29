# Kalasalingam Student Marketplace

A university-exclusive second-hand marketplace for Kalasalingam University students to discover, sell, rent, and discuss useful campus items.

## Included

- University-domain registration with hashed passwords, login/logout, CSRF protection, and role checks
- Google OpenID Connect sign-in for verified Kalasalingam University email addresses
- Approved listing marketplace with search, category, condition, price, listing-type filters, sorting, pagination, and responsive cards
- Secure multi-image uploads with extension validation and generated filenames
- Buy request workflow, rental requests with overlap prevention, wishlist, reports, direct messaging, and rental history
- Separate admin console for user verification/suspension, listing approval/rejection, reports, and categories
- Seed categories and development admin account
- SQLite fallback for quick local development; MySQL is supported through `DATABASE_URL`

## Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Create the MySQL database:

```sql
CREATE DATABASE kalasalingam_marketplace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Update `.env` with a random `SECRET_KEY`, MySQL connection string, and the university email domain. The default domain is `klu.ac.in`; adjust it if the university uses another configured domain.

For Google sign-in, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`. Configure the Google OAuth web client with the authorized origin `http://127.0.0.1:5000` and redirect URI `http://127.0.0.1:5000/login/google/callback`. Google-created accounts are regular student accounts and remain subject to the existing administrator verification process.

Email notifications are sent through the Resend HTTPS API. Configure `RESEND_API_KEY` and `RESEND_FROM` in the deployment environment (or local `.env`); when `RESEND_TEST_MODE=false`, `RESEND_FROM` must be an authorized production sender. To test without a domain, set `RESEND_TEST_MODE=true`. In this mode the application always uses Resend's documented `onboarding@resend.dev` sender and `delivered@resend.dev` recipient; any other `RESEND_TEST_RECIPIENT` value is rejected so real student addresses cannot receive test messages. Test mode confirms provider acceptance only, not inbox delivery. Turn test mode off for real notifications.

Set `ADMIN_NOTIFICATION_EMAIL` to the administrator inbox. If it is unset, the application uses `SUPPORT_EMAIL`, then `MAIL_USERNAME`, as the admin-notification fallback. `MAIL_USERNAME` is also retained as a fallback support address; set `SUPPORT_EMAIL` for a separate support inbox. The legacy `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, and `MAIL_PASSWORD` settings are not used to send notifications.

Successful student registration sends a welcome email and an administrator verification notice. Admin verification sends a separate account-verification email; account verification remains distinct from activation and suspension. Notification failures are logged and do not roll back account changes. Set `PUBLIC_BASE_URL` to the canonical HTTPS application origin when deploying; it is used to generate marketplace links.

Run the seed script and app:

```powershell
python seed.py
python run.py
```

Visit `http://127.0.0.1:5000`.

## Development account

The seed script creates `admin@klu.ac.in` with password `ChangeMe123!`. This is for local development only. Change it immediately before any deployment. Students must register with a valid configured university email and are verified by an admin before publishing listings.

## Project structure

`app/__init__.py` creates the app and extensions. `app/models.py` contains normalized SQLAlchemy models. Auth, product, rental, messaging, and admin behavior live in Flask blueprints under `app/`. Templates and assets are in `app/templates` and `app/static`.

## Production notes

Use MySQL, a strong secret from a secret manager, HTTPS, a production WSGI server, database migrations, backups, and object storage for images. The included SQLite fallback is intended for development smoke tests only.
