import tempfile
import unittest
from pathlib import Path

from app import create_app
from app.category_defaults import DEFAULT_CATEGORY_NAMES
from app.extensions import db
from app.models import Category, Product, User
from config import Config


class PersistentCategoryTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


class CategoryDropdownTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "marketplace.sqlite"
        self.config_class = type(
            "PersistentCategoryTestConfig",
            (PersistentCategoryTestConfig,),
            {
                "SQLALCHEMY_DATABASE_URI": (
                    f"sqlite:///{self.database_path.as_posix()}"
                )
            },
        )
        self.app = create_app(self.config_class)
        self.apps = [self.app]
        self.client = self.app.test_client()

        with self.app.app_context():
            self.assertTrue(self.database_path.is_file())
            student = User(
                name="Category Test Student",
                registration_number="CATEGORY-001",
                university_email="category-test@klu.ac.in",
                department="CSE",
                section="A",
                role="student",
                is_verified=True,
                is_active=True,
            )
            student.set_password("StudentPass123")
            self.category = Category(name="Student Supplies")
            db.session.add_all([student, self.category])
            db.session.commit()
            self.category_id = self.category.id

        self.client.post(
            "/login",
            data={
                "email": "category-test@klu.ac.in",
                "password": "StudentPass123",
            },
        )

    def tearDown(self):
        for app in self.apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        self.tempdir.cleanup()

    def test_startup_initializes_categories_once_in_persistent_database(self):
        with self.app.app_context():
            categories_before_restart = Category.query.count()

        restarted_app = create_app(self.config_class)
        self.apps.append(restarted_app)
        with restarted_app.app_context():
            categories_after_restart = Category.query.count()
            self.assertEqual(categories_after_restart, categories_before_restart)
            self.assertEqual(
                {category.name for category in Category.query.all()},
                set(DEFAULT_CATEGORY_NAMES) | {"Student Supplies"},
            )

    def test_list_page_renders_categories_and_saves_selected_category(self):
        with self.app.app_context():
            categories = Category.ordered()
            self.assertEqual(
                {category.name for category in categories},
                set(DEFAULT_CATEGORY_NAMES) | {"Student Supplies"},
            )
            others = categories[-1]
            self.assertEqual(others.name, "Other")
            self.assertEqual(others.display_name, "Others")
            self.assertEqual(
                [category.display_name for category in categories][-1],
                "Others",
            )

        page = self.client.get("/product/create")
        self.assertEqual(page.status_code, 200)
        page_text = page.get_data(as_text=True)
        for category in categories:
            self.assertIn(
                f'<option value="{category.id}">{category.display_name}</option>',
                page_text,
            )
        self.assertLess(page_text.index(">Others</option>"), page_text.index("</select>"))
        self.assertNotIn(">Other</option>", page_text)

        response = self.client.post(
            "/product/create",
            data={
                "title": "Selected Category Item",
                "description": "A test item in the selected category.",
                "category_id": str(others.id),
                "price": "25.00",
                "listing_type": "sale",
                "condition": "Good",
                "location": "Campus",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            product = Product.query.filter_by(title="Selected Category Item").one()
            self.assertEqual(product.category_id, others.id)


if __name__ == "__main__":
    unittest.main()
