import json
import re
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from users import emails

User = get_user_model()


class EmailStatusHeroTests(TestCase):
    def test_email_templates_contain_no_emoji_characters(self):
        email_senders = (
            (emails.send_welcome_email, ('Customer', 'customer@example.com')),
            (emails.send_admin_new_order_email, ('ORD-1', 'Customer', 'customer@example.com', '100', [], 'Kampala')),
            (emails.send_order_placed_email, ('Customer', 'customer@example.com', 'ORD-1', '100', [], 'Kampala')),
            (emails.send_order_confirmed_email, ('Customer', 'customer@example.com', 'ORD-1', '100', [], 'Kampala')),
            (emails.send_order_shipped_email, ('Customer', 'customer@example.com', 'ORD-1', 'Kampala')),
            (emails.send_order_ready_for_pickup_email, ('Customer', 'customer@example.com', 'ORD-1')),
            (emails.send_order_delivered_email, ('Customer', 'customer@example.com', 'ORD-1')),
            (emails.send_product_rating_email, ('Customer', 'customer@example.com', 'ORD-1', [])),
            (emails.send_order_rating_email, ('Customer', 'customer@example.com', 'ORD-1', 'https://example.com/rate')),
            (emails.send_order_cancelled_email, ('Customer', 'customer@example.com', 'ORD-1', 'Out of stock')),
            (emails.send_password_reset_email, ('Customer', 'customer@example.com', 'https://example.com/reset')),
            (emails.send_password_changed_email, ('Customer', 'customer@example.com')),
            (emails.send_payment_successful_email, ('Customer', 'customer@example.com', 'ORD-1', '100', [])),
            (emails.send_payment_failed_email, ('Customer', 'customer@example.com', 'ORD-1', '100')),
            (emails.send_return_approved_email, ('customer@example.com', 'ORD-1')),
            (emails.send_refund_processed_email, ('customer@example.com', 'ORD-1')),
            (emails.send_trader_approved_email, ('Customer', 'customer@example.com', 'Majo Store', 'trader-1')),
        )
        emoji_pattern = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF]')

        for sender, args in email_senders:
            with self.subTest(sender=sender.__name__), patch.object(emails, '_send') as send:
                sender(*args)
                payload = send.call_args.args[0]

                self.assertIsNone(emoji_pattern.search(payload['subject']))
                self.assertIsNone(emoji_pattern.search(payload['html']))

    def test_trader_approved_email_uses_bullets_instead_of_plus_signs(self):
        with patch.object(emails, '_send') as send:
            emails.send_trader_approved_email('Customer', 'customer@example.com', 'Majo Store', 'trader-1')
            html = send.call_args.args[0]['html']

        self.assertIn('<ul', html)
        self.assertIn('<li', html)
        self.assertIn('List and sell your products on Majo Gadgets', html)
        self.assertNotIn('>+<', html)

    def test_status_hero_uses_matching_image_and_full_width_layout(self):
        html = emails._status_hero('shipped')

        self.assertIn(emails._STEP_IMGS[2][1], html)
        self.assertIn('alt="Order status: Shipped"', html)
        self.assertIn('width:100%;max-width:360px', html)
        self.assertNotIn('Order Progress', html)

    def test_all_order_status_emails_use_status_image_hero(self):
        email_senders = (
            (emails.send_order_placed_email, ('Customer', 'customer@example.com', 'ORD-1', '100', [], 'Kampala'), 'pending'),
            (emails.send_order_confirmed_email, ('Customer', 'customer@example.com', 'ORD-1', '100', [], 'Kampala'), 'processing'),
            (emails.send_order_shipped_email, ('Customer', 'customer@example.com', 'ORD-1', 'Kampala'), 'shipped'),
            (emails.send_order_ready_for_pickup_email, ('Customer', 'customer@example.com', 'ORD-1'), 'ready_for_pickup'),
            (emails.send_order_delivered_email, ('Customer', 'customer@example.com', 'ORD-1'), 'delivered'),
            (emails.send_payment_successful_email, ('Customer', 'customer@example.com', 'ORD-1', '100', [], 'Mobile Money'), 'processing'),
        )

        for sender, args, status in email_senders:
            with self.subTest(status=status), patch.object(emails, '_send') as send:
                sender(*args)
                html = send.call_args.args[0]['html']
                image_url = next(image for key, image, _ in emails._STEP_IMGS if key == status)

                self.assertIn(image_url, html)
                self.assertNotIn('🚚', html)
                self.assertNotIn('Order Progress', html)


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
