import json
import re
from unittest.mock import Mock, patch

import base64
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.test import APIClient

from users import emails
from users.models import EmailMfaChallenge, EmailMfaTrustedDevice

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
            (emails.send_login_verification_email, ('Staff', 'staff@example.com', '123456')),
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

    def test_admin_new_order_email_uses_admin_alias_for_recipient_and_reply(self):
        with patch.object(emails, '_send') as send:
            emails.send_admin_new_order_email('ORD-1', 'Customer', 'customer@example.com', '1000', [], 'Kampala')

        payload = send.call_args.args[0]
        self.assertEqual(payload['to'], emails.settings.ADMIN_EMAIL)
        self.assertEqual(payload['reply_to'], emails.settings.ADMIN_EMAIL)

    def test_customer_transactional_email_replies_to_support_alias(self):
        with patch.object(emails.resend.Emails, 'send') as send:
            emails._send({'from': emails.FROM, 'to': 'customer@example.com', 'subject': 'Test', 'html': 'Test'})

        payload = send.call_args.args[0]
        self.assertEqual(payload['reply_to'], emails.settings.SUPPORT_EMAIL)


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


class EmailMfaLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='staff@example.com',
            name='Staff User',
            password='strong-password-123',
            is_staff=True,
        )

    @patch('users.views.send_login_verification_email')
    def test_staff_login_requires_email_code_before_tokens_are_issued(self, send_code):
        response = self.client.post('/api/auth/login/', {
            'email': self.user.email,
            'password': 'strong-password-123',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['mfa_required'])
        self.assertNotIn('access', response.data)
        self.assertEqual(response.data['email_hint'], 's***@example.com')
        send_code.assert_called_once()
        self.assertEqual(send_code.call_args.args[1], self.user.email)
        self.assertEqual(len(send_code.call_args.args[2]), 6)
        self.assertTrue(send_code.call_args.args[2].isdigit())

    @patch('users.emails._send')
    def test_login_code_email_contains_copy_guidance_and_escapes_code(self, send_email):
        emails.send_login_verification_email('<Staff>', 'staff@example.com', '<123>')
        payload = send_email.call_args.args[0]

        self.assertIn('Hi there,', payload['html'])
        self.assertIn('Your verification code', payload['html'])
        self.assertIn('aria-label="Select code to copy"', payload['html'])
        self.assertIn('Select to copy', payload['html'])
        self.assertIn('Select the code to copy it.', payload['html'])
        self.assertIn('&lt;123&gt;', payload['html'])
        self.assertNotIn('<123>', payload['html'])
        self.assertIn("Didn't request this code?", payload['html'])
        self.assertIn('The Majo Gadgets Team', payload['html'])
        self.assertEqual(payload['to'], 'staff@example.com')

    @patch('users.views.send_login_verification_email')
    def test_valid_code_issues_mfa_tokens_and_seven_day_trusted_device(self, send_code):
        challenge_response = self.client.post('/api/auth/login/', {
            'email': self.user.email,
            'password': 'strong-password-123',
        }, format='json')
        challenge = EmailMfaChallenge.objects.get(challenge_id=challenge_response.data['challenge_id'])

        verified = self.client.post('/api/auth/login/email-code/verify/', {
            'challenge_id': challenge_response.data['challenge_id'],
            'code': send_code.call_args.args[2],
            'remember_device': True,
        }, format='json')

        self.assertEqual(verified.status_code, 200)
        self.assertIn('access', verified.data)
        self.assertIn('refresh', verified.data)
        self.assertIn('trusted_device', verified.data)
        self.assertEqual(EmailMfaTrustedDevice.objects.filter(user=self.user).count(), 1)
        trusted_device = EmailMfaTrustedDevice.objects.get(user=self.user)
        self.assertGreater(trusted_device.expires_at, timezone.now() + timedelta(days=6, hours=23))
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.consumed_at)

    @patch('users.views.send_login_verification_email')
    def test_valid_trusted_device_skips_code_for_seven_days(self, send_code):
        challenge_response = self.client.post('/api/auth/login/', {
            'email': self.user.email,
            'password': 'strong-password-123',
        }, format='json')
        verified = self.client.post('/api/auth/login/email-code/verify/', {
            'challenge_id': challenge_response.data['challenge_id'],
            'code': send_code.call_args.args[2],
            'remember_device': True,
        }, format='json')

        send_code.reset_mock()
        repeated = self.client.post('/api/auth/login/', {
            'email': self.user.email,
            'password': 'strong-password-123',
            'trusted_device': verified.data['trusted_device'],
        }, format='json')

        self.assertEqual(repeated.status_code, 200)
        self.assertIn('access', repeated.data)
        self.assertNotIn('mfa_required', repeated.data)
        send_code.assert_not_called()

    @patch('users.views.send_login_verification_email')
    def test_wrong_code_is_rejected_and_attempt_counted(self, send_code):
        challenge_response = self.client.post('/api/auth/login/', {
            'email': self.user.email,
            'password': 'strong-password-123',
        }, format='json')

        response = self.client.post('/api/auth/login/email-code/verify/', {
            'challenge_id': challenge_response.data['challenge_id'],
            'code': '000000' if send_code.call_args.args[2] != '000000' else '000001',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        challenge = EmailMfaChallenge.objects.get(challenge_id=challenge_response.data['challenge_id'])
        self.assertEqual(challenge.failed_attempts, 1)

    def test_approved_trader_login_requires_email_code(self):
        from traders.models import TraderApplication

        trader = User.objects.create_user(
            email='trader@example.com', name='Trader', password='trader-password-123',
        )
        TraderApplication.objects.create(
            full_name='Trader',
            email=trader.email,
            phone='+256700000000',
            business_name='Trader Store',
            business_type='sole_proprietor',
            location='Kampala',
            product_categories='Electronics',
            user=trader,
            status='approved',
        )

        with patch('users.views.send_login_verification_email') as send_code:
            response = self.client.post('/api/auth/login/', {
                'email': trader.email,
                'password': 'trader-password-123',
            }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['mfa_required'])
        send_code.assert_called_once()

    def test_customer_login_does_not_require_email_mfa(self):
        customer = User.objects.create_user(
            email='customer@example.com', name='Customer', password='customer-password-123',
        )

        response = self.client.post('/api/auth/login/', {
            'email': customer.email,
            'password': 'customer-password-123',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertNotIn('mfa_required', response.data)

    def test_unverified_legacy_refresh_token_is_rejected_for_staff(self):
        response = self.client.post('/api/auth/token/refresh/', {
            'refresh': str(RefreshToken.for_user(self.user)),
        }, format='json')

        self.assertEqual(response.status_code, 401)

    def test_unverified_legacy_access_token_is_rejected_for_staff(self):
        response = self.client.get(
            '/api/auth/profile/',
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(self.user).access_token)}',
        )

        self.assertEqual(response.status_code, 401)

    @patch('users.views.send_login_verification_email')
    def test_mfa_verified_access_and_refresh_tokens_are_accepted(self, send_code):
        challenge_response = self.client.post('/api/auth/login/', {
            'email': self.user.email,
            'password': 'strong-password-123',
        }, format='json')
        verified = self.client.post('/api/auth/login/email-code/verify/', {
            'challenge_id': challenge_response.data['challenge_id'],
            'code': send_code.call_args.args[2],
        }, format='json')

        profile = self.client.get(
            '/api/auth/profile/',
            HTTP_AUTHORIZATION=f"Bearer {verified.data['access']}",
        )
        refreshed = self.client.post('/api/auth/token/refresh/', {
            'refresh': verified.data['refresh'],
        }, format='json')

        self.assertEqual(profile.status_code, 200)
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn('access', refreshed.data)


class SupportChatApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            email='customer@example.com', name='Customer', password='password-123',
        )
        self.staff = User.objects.create_user(
            email='staff@example.com', name='Support Agent', password='password-123', is_staff=True,
        )

    def register_encryption_key(self, user):
        self.client.force_authenticate(user=user)
        response = self.client.post('/api/auth/support/encryption-keys/', {
            'device_id': str(uuid.uuid4()),
            'public_key': base64.b64encode(bytes([user.id % 255 + 1]) * 32).decode('ascii'),
        }, format='json')
        self.assertEqual(response.status_code, 201)
        return response.data

    def encrypted_envelope(self, sender_key, recipients):
        return {
            'version': 1,
            'sender_key_id': sender_key['key_id'],
            'recipients': [
                {
                    'key_id': key['key_id'],
                    'nonce': base64.b64encode(bytes(24)).decode('ascii'),
                    'ciphertext': base64.b64encode(bytes(16)).decode('ascii'),
                }
                for key in recipients
            ],
        }

    def test_customer_can_send_message_and_staff_can_reply(self):
        customer_key = self.register_encryption_key(self.customer)
        staff_key = self.register_encryption_key(self.staff)

        self.client.force_authenticate(user=self.customer)
        recipients = self.client.get('/api/auth/support/encryption-keys/').data['keys']
        sent = self.client.post('/api/auth/support/chat/', {
            'envelope': self.encrypted_envelope(customer_key, recipients),
        }, format='json')
        self.assertEqual(sent.status_code, 201)
        conversation_id = sent.data['conversation_id']

        self.client.force_authenticate(user=self.staff)
        inbox = self.client.get('/api/auth/admin/support/conversations/')
        self.assertEqual(inbox.status_code, 200)
        self.assertEqual(inbox.data[0]['unread_count'], 1)
        recipients = self.client.get(
            f'/api/auth/support/encryption-keys/?user_id={self.customer.id}'
        ).data['keys']
        reply = self.client.post(
            f'/api/auth/admin/support/conversations/{conversation_id}/',
            {'envelope': self.encrypted_envelope(staff_key, recipients)},
            format='json',
        )
        self.assertEqual(reply.status_code, 201)

        self.client.force_authenticate(user=self.customer)
        chat = self.client.get('/api/auth/support/chat/?mark_read=true')
        self.assertEqual(chat.status_code, 200)
        self.assertEqual(len(chat.data['messages']), 2)
        self.assertEqual(chat.data['unread_count'], 0)

    def test_chat_requires_authentication_and_staff_routes_require_staff(self):
        self.assertEqual(self.client.get('/api/auth/support/chat/').status_code, 401)

        self.client.force_authenticate(user=self.customer)
        self.assertEqual(self.client.get('/api/auth/admin/support/conversations/').status_code, 403)

    def test_customer_can_start_empty_conversation_before_sending(self):
        self.register_encryption_key(self.customer)
        self.client.force_authenticate(user=self.customer)
        self.assertIsNone(self.client.get('/api/auth/support/chat/').data['conversation_id'])

        started = self.client.post('/api/auth/support/chat/', {'start': True}, format='json')
        self.assertEqual(started.status_code, 201)
        conversation_id = started.data['conversation_id']

        repeated = self.client.post('/api/auth/support/chat/', {'start': True}, format='json')
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data['conversation_id'], conversation_id)

        self.client.force_authenticate(user=self.staff)
        inbox = self.client.get('/api/auth/admin/support/conversations/')
        self.assertEqual(len(inbox.data), 1)
        self.assertEqual(inbox.data[0]['id'], conversation_id)
        self.assertIsNone(inbox.data[0]['last_message'])

    def test_customer_must_register_encryption_key_before_starting_chat(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/auth/support/chat/', {'start': True}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('Register this device', response.data['detail'])
        self.assertIsNone(self.client.get('/api/auth/support/chat/').data['conversation_id'])

    def test_customer_message_rejects_blank_content(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/auth/support/chat/', {'body': '  '}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_encryption_key_directory_is_limited_to_customer_and_support_staff(self):
        customer_key = self.register_encryption_key(self.customer)
        staff_key = self.register_encryption_key(self.staff)
        other_customer = User.objects.create_user(
            email='other-customer@example.com', name='Other Customer', password='password-123',
        )
        self.register_encryption_key(other_customer)

        self.client.force_authenticate(user=self.customer)
        customer_keys = self.client.get('/api/auth/support/encryption-keys/').data['keys']
        self.assertEqual({key['key_id'] for key in customer_keys}, {customer_key['key_id'], staff_key['key_id']})

        self.client.force_authenticate(user=self.staff)
        staff_keys = self.client.get(
            f'/api/auth/support/encryption-keys/?user_id={self.customer.id}'
        ).data['keys']
        self.assertEqual({key['key_id'] for key in staff_keys}, {customer_key['key_id'], staff_key['key_id']})

    def test_support_key_backup_is_private_and_validated(self):
        url = '/api/auth/support/encryption-backup/'
        self.client.force_authenticate(user=self.customer)
        self.assertIsNone(self.client.get(url).data['backup'])

        invalid = self.client.put(url, {'backup': {'version': 1}}, format='json')
        self.assertEqual(invalid.status_code, 400)

        backup = {
            'version': 1,
            'kdf': 'PBKDF2-SHA256',
            'iterations': 600_000,
            'device_id': str(uuid.uuid4()),
            'salt': base64.b64encode(bytes(16)).decode('ascii'),
            'ciphertext': base64.b64encode(bytes(28)).decode('ascii'),
        }
        saved = self.client.put(url, {'backup': backup}, format='json')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.data['backup'], backup)
        conflicting_backup = {**backup, 'device_id': str(uuid.uuid4())}
        conflict = self.client.put(url, {'backup': conflicting_backup}, format='json')
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get(url).data['backup'], backup)

        self.client.force_authenticate(user=self.staff)
        self.assertIsNone(self.client.get(url).data['backup'])

    def test_support_key_backup_requires_authentication(self):
        response = self.client.get('/api/auth/support/encryption-backup/')
        self.assertEqual(response.status_code, 401)

    def test_plaintext_support_messages_are_rejected(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/auth/support/chat/', {'body': 'plaintext'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_encrypted_messages_reject_unrelated_and_duplicate_recipients(self):
        customer_key = self.register_encryption_key(self.customer)
        self.register_encryption_key(self.staff)
        other_customer = User.objects.create_user(
            email='unrelated-customer@example.com', name='Unrelated Customer', password='password-123',
        )
        unrelated_key = self.register_encryption_key(other_customer)

        self.client.force_authenticate(user=self.customer)
        recipients = self.client.get('/api/auth/support/encryption-keys/').data['keys']
        envelope = self.encrypted_envelope(customer_key, recipients + [unrelated_key])
        response = self.client.post('/api/auth/support/chat/', {'envelope': envelope}, format='json')
        self.assertEqual(response.status_code, 409)

        envelope = self.encrypted_envelope(customer_key, recipients)
        envelope['recipients'].append(envelope['recipients'][0].copy())
        response = self.client.post('/api/auth/support/chat/', {'envelope': envelope}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_staff_without_support_assignment_cannot_open_inbox(self):
        self.staff.assigned_pages = ['Orders']
        self.staff.save(update_fields=['assigned_pages'])
        self.client.force_authenticate(user=self.staff)
        response = self.client.get('/api/auth/admin/support/conversations/')
        self.assertEqual(response.status_code, 403)

    def test_typing_status_is_visible_to_the_other_participant(self):
        customer_key = self.register_encryption_key(self.customer)
        staff_key = self.register_encryption_key(self.staff)

        self.client.force_authenticate(user=self.customer)
        recipients = self.client.get('/api/auth/support/encryption-keys/').data['keys']
        sent = self.client.post('/api/auth/support/chat/', {
            'envelope': self.encrypted_envelope(customer_key, recipients),
        }, format='json')
        conversation_id = sent.data['conversation_id']
        self.client.patch('/api/auth/support/chat/', {'is_typing': True}, format='json')

        self.client.force_authenticate(user=self.staff)
        staff_view = self.client.get(f'/api/auth/admin/support/conversations/{conversation_id}/')
        self.assertTrue(staff_view.data['customer_typing'])
        self.client.patch(
            f'/api/auth/admin/support/conversations/{conversation_id}/',
            {'is_typing': True},
            format='json',
        )

        self.client.force_authenticate(user=self.customer)
        customer_view = self.client.get('/api/auth/support/chat/')
        self.assertTrue(customer_view.data['staff_typing'])


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
