import io
import os
import unittest

from PIL import Image

from app import create_app
from app.extensions import db
from app.models import AdminProduct, User
from config import Config


class KluStoreImageUploadTests(unittest.TestCase):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    def setUp(self):
        self.app = create_app(self.TestConfig)
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()
            admin = User(
                name='Marketplace Admin',
                registration_number='ADMIN-001',
                university_email='admin@klu.ac.in',
                department='Administration',
                section='A',
                role='admin',
                is_verified=True,
                is_active=True,
            )
            admin.set_password('ChangeMe123!')
            db.session.add(admin)
            db.session.commit()

    def tearDown(self):
        if hasattr(self, "uploaded_image_path") and os.path.exists(
            self.uploaded_image_path
        ):
            os.remove(self.uploaded_image_path)
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_admin_store_upload_saves_to_static_uploads_and_serves_url(self):
        with self.app.app_context():
            admin = User.query.filter_by(university_email='admin@klu.ac.in').first()
            with self.client.session_transaction() as session:
                session['_user_id'] = str(admin.id)
                session['_fresh'] = True

            image_bytes = io.BytesIO()
            Image.new('RGB', (40, 40), color='red').save(image_bytes, format='PNG')
            image_bytes.seek(0)

            response = self.client.post(
                '/klu-store/admin/add',
                data={
                    'title': 'Upload Check',
                    'description': 'Test product image upload',
                    'category': 'Accessories',
                    'price': '299',
                    'stock': '5',
                    'image': (image_bytes, 'upload-check.png'),
                },
                content_type='multipart/form-data',
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 302)
            with self.app.app_context():
                product = AdminProduct.query.filter_by(title='Upload Check').first()
                self.assertIsNotNone(product)
                self.assertIsNotNone(product.image_path)
                self.assertTrue(product.image_path.startswith('uploads/'))
                self.assertIn('upload-check', product.image_path)
                full_path = os.path.join(self.app.config['UPLOAD_FOLDER'], product.image_path.replace('uploads/', ''))
                self.uploaded_image_path = full_path
                self.assertTrue(os.path.exists(full_path))
                self.assertTrue(product.image_url.startswith('/static/uploads/'))
                static_response = self.client.get(product.image_url)
                self.assertEqual(static_response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
