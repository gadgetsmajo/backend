import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from users import emails

User = get_user_model()


class EmailProgressTemplateTests(TestCase):
    def test_order_progress_bar_contains_all_steps_and_active_line(self):
        html = emails._progress_bar('shipped')

        self.assertIn('Order Progress', html)
        self.assertIn('Placed', html)
        self.assertIn('Confirmed', html)
        self.assertIn('Shipped', html)
        self.assertIn('Delivered', html)
        self.assertIn('#F59E0B', html)
        self.assertIn('#E2E8F0', html)


class ProfilePasswordFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='admin@example.com',
            name='Admin User',
            password='old-password-123',
            is_staff=True,
        )
        self.client.force_authenticate(user=self.user)

    def test_profile_update_accepts_current_password_and_new_password(self):
        response = self.client.patch(
            '/api/auth/profile/',
            {
                'current_password': 'old-password-123',
                'new_password': 'new-password-456',
                'password_confirm': 'new-password-456',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('new-password-456'))

    def test_profile_update_rejects_wrong_current_password(self):
        response = self.client.patch(
            '/api/auth/profile/',
            {
                'current_password': 'wrong-password',
                'new_password': 'new-password-456',
                'password_confirm': 'new-password-456',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('current_password', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-password-123'))


class GoogleLoginAvatarTests(TestCase):
    @patch('cloudinary.uploader.upload')
    @patch('urllib.request.urlopen')
    def test_google_login_stores_verified_profile_picture(self, mock_urlopen, mock_upload):
        userinfo = {
            'email': 'google-user@example.com',
            'name': 'Google User',
            'picture': 'https://lh3.googleusercontent.com/a/google-user-photo',
        }
        response_body = Mock()
        response_body.read.return_value = json.dumps(userinfo).encode()
        mock_urlopen.return_value.__enter__.return_value = response_body
        mock_upload.return_value = {'public_id': 'avatars/google-user'}

        response = APIClient().post(
            '/api/auth/login/google/',
            {'credential': 'google-access-token'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='google-user@example.com')
        self.assertEqual(str(user.avatar), 'avatars/google-user')
        mock_upload.assert_called_once_with(
            userinfo['picture'],
            folder='avatars/',
        )
