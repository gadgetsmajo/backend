from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from orders.models import Order, Payment, ReturnRequest

User = get_user_model()


class OrderDeliveryEmailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email='admin@example.com',
            name='Admin User',
            password='Password123!',
        )
        self.user = User.objects.create_user(
            email='customer@example.com',
            name='Jane Doe',
            password='Password123!',
        )
        self.order = Order.objects.create(
            user=self.user,
            code='12345678-ABCD',
            status='shipped',
            total=25000,
            delivery_address='Kampala, Uganda',
            phone='+256700000000',
        )

    @patch('orders.views.send_product_rating_notifications.apply_async')
    @patch('orders.views.send_order_rating_email')
    @patch('orders.views.send_order_delivered_email')
    def test_admin_deliver_view_sends_rating_email(self, mock_delivered, mock_rating, mock_queue):
        self.client.force_authenticate(user=self.admin)
        self.order.status = 'ready_for_pickup'
        self.order.save(update_fields=['status'])

        response = self.client.post(f'/api/orders/admin/{self.order.code}/deliver/')

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'delivered')
        mock_delivered.assert_called_once_with(
            self.user.name,
            self.user.email,
            self.order.code,
            f'{self.order.total:,.0f}',
            [],
            self.order.delivery_address,
        )
        mock_queue.assert_called_once_with((self.order.id,), countdown=300)
        mock_rating.assert_not_called()

    def test_admin_order_and_payment_lists_return_200(self):
        self.client.force_authenticate(user=self.admin)
        self.order.status_changed_by = self.admin
        self.order.save(update_fields=['status_changed_by'])
        Payment.objects.create(
            order=self.order,
            pesapal_order_tracking_id='track-123',
            amount=self.order.total,
            status='completed',
            payment_method='Pesapal',
        )

        orders_response = self.client.get('/api/orders/admin/')
        payments_response = self.client.get('/api/orders/admin/payments/')

        self.assertEqual(orders_response.status_code, 200)
        self.assertEqual(payments_response.status_code, 200)
        self.assertEqual(payments_response.json()['results'][0]['order_code'], self.order.code)

    def test_admin_lists_handle_null_related_fields(self):
        self.client.force_authenticate(user=self.admin)
        Payment.objects.create(
            order=None,
            pesapal_order_tracking_id='track-null-order',
            amount=25000,
            status='completed',
            payment_method='Pesapal',
        )
        self.order.status_changed_by = None
        self.order.save(update_fields=['status_changed_by'])

        orders_response = self.client.get('/api/orders/admin/')
        payments_response = self.client.get('/api/orders/admin/payments/')

        self.assertEqual(orders_response.status_code, 200)
        self.assertEqual(payments_response.status_code, 200)
        self.assertIsNone(orders_response.json()['results'][0]['status_changed_by_name'])
        self.assertIsNone(payments_response.json()['results'][-1]['order_code'])


class ReturnRequestAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email='returns-admin@example.com', name='Returns Admin', password='Password123!'
        )
        self.user = User.objects.create_user(
            email='return-customer@example.com', name='Return Customer', password='Password123!'
        )
        self.order = Order.objects.create(user=self.user, code='87654321-ABCD', status='delivered', total=25000)
        self.payment = Payment.objects.create(
            order=self.order, pesapal_order_tracking_id='track-return-123', confirmation_code='confirm-123', amount=25000, status='completed', payment_method='Mobile Money'
        )
        self.return_request = ReturnRequest.objects.create(order=self.order, reason='Item arrived damaged')
        self.client.force_authenticate(user=self.admin)

    @patch('orders.views.send_return_approved_email')
    @patch('orders.views.http_requests.post')
    @patch('orders.views._pesapal_token', return_value='pesapal-token')
    @override_settings(PESAPAL_REFUND_USERNAME='merchant-user')
    def test_approval_requests_refund_for_original_payment(self, mock_token, mock_post, mock_email):
        mock_post.return_value.json.return_value = {'status': '200', 'message': 'Refund request successfully'}
        mock_post.return_value.raise_for_status.return_value = None

        response = self.client.post(f'/api/orders/admin/returns/{self.return_request.id}/approve/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'approved')
        self.assertIn('refund request has been accepted', response.json()['admin_note'])
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs['json']['confirmation_code'], self.payment.confirmation_code)
        self.assertEqual(mock_post.call_args.kwargs['json']['amount'], float(self.payment.amount))
        mock_email.assert_called_once_with(self.user.email, self.order.code)

    @patch('orders.views.http_requests.get')
    @patch('orders.views._pesapal_token', return_value='pesapal-token')
    def test_ipn_persists_provider_confirmation_code(self, mock_token, mock_get):
        self.payment.status = 'pending'
        self.payment.save(update_fields=['status'])
        mock_get.return_value.json.return_value = {
            'amount': 25000,
            'payment_status_description': 'pending',
            'confirmation_code': 'confirm-from-provider',
        }
        mock_get.return_value.raise_for_status.return_value = None

        response = self.client.get(
            f'/api/orders/pesapal/ipn/?OrderTrackingId={self.payment.pesapal_order_tracking_id}'
            f'&OrderMerchantReference={self.payment.merchant_reference}'
        )

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.confirmation_code, 'confirm-from-provider')

    @patch('orders.views.send_return_approved_email')
    @patch('orders.views.http_requests.post')
    @patch('orders.views._pesapal_token', return_value='pesapal-token')
    @override_settings(PESAPAL_REFUND_USERNAME='merchant-user')
    def test_provider_failure_does_not_mark_return_approved(self, mock_token, mock_post, mock_email):
        mock_post.return_value.json.return_value = {'error': {'message': 'Refunds not enabled'}}
        mock_post.return_value.raise_for_status.return_value = None

        response = self.client.post(f'/api/orders/admin/returns/{self.return_request.id}/approve/')

        self.assertEqual(response.status_code, 502)
        self.return_request.refresh_from_db()
        self.assertEqual(self.return_request.status, 'refund_failed')
        mock_email.assert_not_called()

    @patch('orders.views.http_requests.get')
    @patch('orders.views.http_requests.post')
    @patch('orders.views.send_return_approved_email')
    @patch('orders.views._pesapal_token', return_value='pesapal-token')
    @override_settings(PESAPAL_REFUND_USERNAME='merchant-user')
    def test_approval_fetches_confirmation_code_for_older_payment(self, mock_token, mock_email, mock_post, mock_get):
        self.payment.confirmation_code = ''
        self.payment.save(update_fields=['confirmation_code'])
        mock_get.return_value.json.return_value = {
            'amount': 25000,
            'payment_status_description': 'Completed',
            'confirmation_code': 'legacy-confirm-code',
        }
        mock_get.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {'status': '200', 'message': 'Refund request successfully'}
        mock_post.return_value.raise_for_status.return_value = None

        response = self.client.post(f'/api/orders/admin/returns/{self.return_request.id}/approve/')

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.confirmation_code, 'legacy-confirm-code')
        self.assertEqual(mock_post.call_args.kwargs['json']['confirmation_code'], 'legacy-confirm-code')
        mock_email.assert_called_once()

    @patch('orders.views.send_refund_processed_email')
    def test_refunded_confirmation_sends_final_email_once(self, mock_email):
        self.return_request.status = 'approved'
        self.return_request.refund_amount = self.payment.amount
        self.return_request.save(update_fields=['status', 'refund_amount'])

        response = self.client.post(f'/api/orders/admin/returns/{self.return_request.id}/refunded/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'refunded')
        mock_email.assert_called_once_with(self.user.email, self.order.code)

        duplicate_response = self.client.post(f'/api/orders/admin/returns/{self.return_request.id}/refunded/')

        self.assertEqual(duplicate_response.status_code, 400)
        mock_email.assert_called_once()
