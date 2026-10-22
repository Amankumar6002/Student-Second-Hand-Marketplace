# Kalasalingam Student Marketplace

A university-exclusive second-hand marketplace for Kalasalingam University students to discover, sell, rent, and discuss useful campus items.

## Included

- University-domain registration with hashed passwords, login/logout, CSRF protection, and role checks
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
Copy-Item .env.example .env
```

Create the MySQL database:

```sql
CREATE DATABASE kalasalingam_marketplace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Update `.env` with a random `SECRET_KEY`, MySQL connection string, and the university email domain. The default domain is `klu.ac.in`; adjust it if the university uses another configured domain.

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
