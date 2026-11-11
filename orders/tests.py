from unittest.mock import patch
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounting.models import Refund as AccountingRefund
from orders.models import Order, OrderItem, Payment, ReturnRequest
from products.models import Product, ProductVariant
from settings_app.models import District, PlatformSettings
from users.models import CartItem, Notification

User = get_user_model()


class PesapalBillingNameTests(TestCase):
    @override_settings(
        PESAPAL_CONSUMER_KEY='test-key',
        PESAPAL_CONSUMER_SECRET='test-secret',
        PESAPAL_IPN_URL='https://example.com/ipn',
        PESAPAL_CALLBACK_URL='https://example.com/callback',
    )
    def test_submit_payload_includes_non_empty_middle_name(self):
        user = User.objects.create_user(
            email='jane@example.com', name='Jane Doe', password='Password123!',
        )
        order = Order.objects.create(
            user=user,
            code='PAYMENT-NAME-001',
            status='pending',
            total=25000,
            delivery_address='Kampala, Uganda',
            phone='+256700000000',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=user)

        with (
            patch('orders.views._pesapal_token', return_value='pesapal-token'),
            patch('orders.views._register_ipn', return_value='ipn-id'),
            patch('orders.views.http_requests.post') as mock_submit,
        ):
            mock_submit.return_value.json.return_value = {
                'redirect_url': 'https://pesapal.example/checkout',
                'order_tracking_id': 'tracking-id',
            }
            response = self.client.post(f'/api/orders/{order.code}/pay/')

        self.assertEqual(response.status_code, 200)
        billing_address = mock_submit.call_args.kwargs['json']['billing_address']
        self.assertEqual(billing_address['first_name'], 'Jane')
        self.assertEqual(billing_address['middle_name'], 'NA')
        self.assertEqual(billing_address['last_name'], 'Doe')
        self.assertEqual(billing_address['line_1'], 'Kampala, Uganda')
        self.assertEqual(billing_address['country_code'], 'UG')
        self.assertEqual(billing_address['city'], 'Kampala')
        self.assertNotIn('address_line_1', billing_address)

    @override_settings(
        PESAPAL_CONSUMER_KEY='test-key',
        PESAPAL_CONSUMER_SECRET='test-secret',
        PESAPAL_IPN_URL='https://example.com/ipn',
        PESAPAL_CALLBACK_URL='https://example.com/callback',
    )
    def test_submit_payload_uses_non_empty_address_for_legacy_order(self):
        user = User.objects.create_user(
            email='legacy@example.com', name='Legacy Customer', password='Password123!',
        )
        order = Order.objects.create(
            user=user,
            code='PAYMENT-ADDRESS-001',
            status='pending',
            total=25000,
            delivery_address=' ',
            phone='+256700000000',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=user)

        with (
            patch('orders.views._pesapal_token', return_value='pesapal-token'),
            patch('orders.views._register_ipn', return_value='ipn-id'),
            patch('orders.views.http_requests.post') as mock_submit,
        ):
            mock_submit.return_value.json.return_value = {
                'redirect_url': 'https://pesapal.example/checkout',
                'order_tracking_id': 'tracking-id',
            }
            response = self.client.post(f'/api/orders/{order.code}/pay/')

        self.assertEqual(response.status_code, 200)
        billing_address = mock_submit.call_args.kwargs['json']['billing_address']
        self.assertEqual(billing_address['line_1'], 'Kampala')
        self.assertEqual(billing_address['country_code'], 'UG')

    @override_settings(
        PESAPAL_CONSUMER_KEY='test-key',
        PESAPAL_CONSUMER_SECRET='test-secret',
        PESAPAL_IPN_URL='https://example.com/ipn',
        PESAPAL_CALLBACK_URL='https://example.com/callback',
    )
    def test_submit_payload_strips_disallowed_middle_name_characters(self):
        user = User.objects.create_user(
            email='mary@example.com', name='Jane Mary Ann/Lee Doe', password='Password123!',
        )
        order = Order.objects.create(
            user=user,
            code='PAYMENT-NAME-002',
            status='pending',
            total=25000,
            delivery_address='Kampala, Uganda',
            phone='+256700000000',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=user)

        with (
            patch('orders.views._pesapal_token', return_value='pesapal-token'),
            patch('orders.views._register_ipn', return_value='ipn-id'),
            patch('orders.views.http_requests.post') as mock_submit,
        ):
            mock_submit.return_value.json.return_value = {
                'redirect_url': 'https://pesapal.example/checkout',
                'order_tracking_id': 'tracking-id',
            }
            response = self.client.post(f'/api/orders/{order.code}/pay/')

        self.assertEqual(response.status_code, 200)
        billing_address = mock_submit.call_args.kwargs['json']['billing_address']
        self.assertEqual(billing_address['middle_name'], 'MaryAnnLee')


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


class OrderPricingSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='pricing-customer@example.com',
            name='Pricing Customer',
            password='Password123!',
        )
        self.product = Product.objects.create(
            name='Secure Price Product',
            price='12000.00',
            delivery_fee='2000.00',
            stock=5,
        )
        self.district = District.objects.create(
            name='Secure District',
            region='Central Region',
            price='10000.00',
        )
        self.cart_item = CartItem.objects.create(
            user=self.user,
            product_id=self.product.id,
            product_name='Fake Product Name',
            product_price='1.00',
            product_image='https://example.com/fake.png',
            product_slug='fake-slug',
            quantity=2,
        )
        self.client.force_authenticate(user=self.user)

    def test_cart_quote_uses_database_prices_and_district_delivery_fee(self):
        response = self.client.post('/api/orders/quote/', {
            'district_id': self.district.id,
            'items': [{'product_id': self.product.id, 'quantity': 5}],
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['subtotal'], Decimal('24000.00'))
        self.assertEqual(response.data['delivery_fee'], Decimal('10000.00'))
        self.assertEqual(response.data['total'], Decimal('34000.00'))
        self.assertEqual(response.data['items'][0]['product_name'], 'Secure Price Product')
        self.assertEqual(response.data['items'][0]['product_price'], Decimal('12000.00'))
        self.assertEqual(response.data['items'][0]['quantity'], 2)

    def test_guest_quote_ignores_client_supplied_prices_and_delivery(self):
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/orders/quote/', {
            'items': [{
                'product_id': self.product.id,
                'quantity': 2,
                'product_price': '1.00',
                'delivery_fee': 0,
            }],
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['subtotal'], Decimal('24000.00'))
        self.assertEqual(response.data['delivery_fee'], Decimal('2000.00'))
        self.assertEqual(response.data['total'], Decimal('26000.00'))

    def test_current_commission_is_used_for_quotes_and_order_price_snapshots(self):
        settings = PlatformSettings.get()
        settings.commission = '10.00'
        settings.save()

        quote = self.client.post('/api/orders/quote/', {
            'district_id': self.district.id,
            'items': [{'product_id': self.product.id, 'quantity': 2}],
        }, format='json')

        self.assertEqual(quote.status_code, 200)
        self.assertEqual(quote.data['items'][0]['product_price'], Decimal('13200.00'))
        self.assertEqual(quote.data['subtotal'], Decimal('26400.00'))

        response = self.client.post('/api/orders/', {
            'district_id': self.district.id,
            'phone': '+256700000000',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        order = Order.objects.get(pk=response.data['id'])
        self.assertEqual(order.subtotal, Decimal('26400.00'))
        self.assertEqual(order.total, Decimal('36400.00'))
        self.assertEqual(order.items.get().price, Decimal('13200.00'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal('12000.00'))

    def test_order_ignores_client_items_address_and_delivery_amount(self):
        response = self.client.post('/api/orders/', {
            'district_id': self.district.id,
            'village': 'Nakasero',
            'delivery_address': 'Fake destination',
            'delivery_fee': 1,
            'items': [{'product_id': self.product.id, 'quantity': 100}],
            'phone': '+256700000000',
            'note': 'Please deliver carefully',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        order = Order.objects.get(pk=response.data['id'])
        self.assertEqual(order.subtotal, 24000)
        self.assertEqual(order.delivery_fee, 10000)
        self.assertEqual(order.total, 34000)
        self.assertEqual(order.delivery_address, 'Central Region, Secure District, Nakasero')
        order_item = order.items.get()
        self.assertEqual(order_item.product, self.product)
        self.assertEqual(order_item.quantity, 2)
        self.assertEqual(order_item.price, 12000)
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())

    def test_order_rejects_unavailable_stock_without_creating_order(self):
        self.cart_item.quantity = 6
        self.cart_item.save(update_fields=['quantity'])

        response = self.client.post('/api/orders/', {
            'district_id': self.district.id,
            'village': '',
            'phone': '+256700000000',
            'note': '',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertTrue(CartItem.objects.filter(user=self.user).exists())

    def test_variant_options_price_stock_and_snapshot_are_used_through_order(self):
        self.cart_item.delete()
        variant = ProductVariant.objects.create(
            product=self.product,
            sku='SHOE-BLACK-42',
            options={'size': '42', 'color': 'Black'},
            price='17500.00',
            stock=3,
        )
        cart_response = self.client.post('/api/auth/cart/', {
            'product_id': self.product.id,
            'variant_id': variant.id,
            'quantity': 2,
        }, format='json')

        self.assertEqual(cart_response.status_code, 201, cart_response.data)
        self.assertEqual(cart_response.data['variant_options'], {'size': '42', 'color': 'Black'})
        quote = self.client.post('/api/orders/quote/', {
            'district_id': self.district.id,
        }, format='json')
        self.assertEqual(quote.status_code, 200, quote.data)
        self.assertEqual(quote.data['items'][0]['variant_id'], variant.id)
        self.assertEqual(quote.data['items'][0]['variant_options'], {'size': '42', 'color': 'Black'})
        self.assertEqual(quote.data['items'][0]['product_price'], Decimal('17500.00'))

        response = self.client.post('/api/orders/', {
            'district_id': self.district.id,
            'phone': '+256700000000',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        order_item = OrderItem.objects.get(order_id=response.data['id'])
        self.assertEqual(order_item.variant, variant)
        self.assertEqual(order_item.variant_options, {'size': '42', 'color': 'Black'})
        self.assertEqual(order_item.variant_sku, 'SHOE-BLACK-42')
        self.assertEqual(order_item.price, quote.data['items'][0]['product_price'])
        self.assertEqual(response.data['items'][0]['variant_options'], {'size': '42', 'color': 'Black'})

    def test_optioned_product_requires_a_variant_and_uses_variant_stock_limit(self):
        variant = ProductVariant.objects.create(
            product=self.product,
            options={'size': '42', 'color': 'Black'},
            price='17500.00',
            stock=1,
        )
        self.cart_item.quantity = 2
        self.cart_item.save(update_fields=['quantity'])
        missing_option = self.client.post('/api/orders/quote/', {
            'district_id': self.district.id,
        }, format='json')
        self.assertEqual(missing_option.status_code, 400)

        self.cart_item.variant = variant
        self.cart_item.variant_options = variant.options
        self.cart_item.save(update_fields=['variant', 'variant_options'])
        insufficient_variant_stock = self.client.post('/api/orders/quote/', {
            'district_id': self.district.id,
        }, format='json')
        self.assertEqual(insufficient_variant_stock.status_code, 400)
        self.assertIn('Available: 1', insufficient_variant_stock.data['detail'])

    def test_guest_quote_prices_the_selected_variant(self):
        variant = ProductVariant.objects.create(
            product=self.product,
            options={'size': '42', 'color': 'Blue'},
            price='19000.00',
            stock=2,
        )
        self.client.force_authenticate(user=None)
        quote = self.client.post('/api/orders/quote/', {
            'district_id': self.district.id,
            'items': [{
                'id': 987654,
                'product_id': self.product.id,
                'variant_id': variant.id,
                'quantity': 1,
            }],
        }, format='json')

        self.assertEqual(quote.status_code, 200, quote.data)
        self.assertEqual(quote.data['items'][0]['id'], 987654)
        self.assertEqual(quote.data['items'][0]['variant_id'], variant.id)
        self.assertEqual(quote.data['items'][0]['variant_options'], {'size': '42', 'color': 'Blue'})
        self.assertEqual(quote.data['items'][0]['product_price'], Decimal('19000.00'))

    def test_cancelling_unpaid_option_order_does_not_restore_unreserved_stock(self):
        variant = ProductVariant.objects.create(
            product=self.product,
            options={'size': '42', 'color': 'Black'},
            price='17500.00',
            stock=3,
        )
        order = Order.objects.create(user=self.user, total='35000.00')
        OrderItem.objects.create(
            order=order,
            product=self.product,
            variant=variant,
            variant_options=variant.options,
            quantity=2,
            price='17500.00',
        )

        response = self.client.post(f'/api/orders/{order.code}/cancel/')

        self.assertEqual(response.status_code, 200, response.data)
        self.product.refresh_from_db()
        variant.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertEqual(variant.stock, 3)

    def test_restoring_paid_option_order_returns_product_and_variant_stock(self):
        from orders.views import _restore_stock

        variant = ProductVariant.objects.create(
            product=self.product,
            options={'size': '42', 'color': 'Black'},
            price='17500.00',
            stock=1,
        )
        order = Order.objects.create(user=self.user, total='35000.00')
        OrderItem.objects.create(
            order=order,
            product=self.product,
            variant=variant,
            variant_options=variant.options,
            quantity=2,
            price='17500.00',
        )
        Payment.objects.create(
            order=order,
            pesapal_order_tracking_id='track-variant-restock',
            amount='35000.00',
            status='completed',
        )
        self.product.stock = 3
        self.product.save(update_fields=['stock'])

        _restore_stock(order)

        self.product.refresh_from_db()
        variant.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertEqual(variant.stock, 3)

    def test_cart_requires_and_keeps_distinct_variant_selections(self):
        self.cart_item.delete()
        variants = [
            ProductVariant.objects.create(
                product=self.product,
                options={'size': size, 'color': 'Black'},
                price='17500.00',
                stock=2,
            )
            for size in ('41', '42')
        ]
        missing_selection = self.client.post('/api/auth/cart/', {
            'product_id': self.product.id,
            'quantity': 1,
        }, format='json')
        self.assertEqual(missing_selection.status_code, 400)

        for variant in variants:
            response = self.client.post('/api/auth/cart/', {
                'product_id': self.product.id,
                'variant_id': variant.id,
                'quantity': 1,
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)

        items = self.client.get('/api/auth/cart/')
        self.assertEqual(items.status_code, 200)
        self.assertEqual({item['variant_id'] for item in items.data}, {variant.id for variant in variants})
        self.assertEqual({item['variant_options']['size'] for item in items.data}, {'41', '42'})


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

    @patch('orders.views.http_requests.get')
    @patch('orders.views._pesapal_token', return_value='pesapal-token')
    def test_ipn_rejects_missing_amount(self, mock_token, mock_get):
        self.payment.status = 'pending'
        self.payment.save(update_fields=['status'])
        mock_get.return_value.json.return_value = {
            'currency_code': 'UGX',
            'payment_status_description': 'Completed',
        }
        mock_get.return_value.raise_for_status.return_value = None

        response = self.client.get(
            f'/api/orders/pesapal/ipn/?OrderTrackingId={self.payment.pesapal_order_tracking_id}'
        )

        self.assertEqual(response.status_code, 400)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'pending')

    @patch('orders.views.http_requests.get')
    @patch('orders.views._pesapal_token', return_value='pesapal-token')
    def test_ipn_rejects_wrong_amount_and_currency(self, mock_token, mock_get):
        for provider_response in (
            {'amount': 0, 'currency_code': 'UGX'},
            {'amount': 25000, 'currency_code': 'USD'},
        ):
            with self.subTest(provider_response=provider_response):
                self.payment.status = 'pending'
                self.payment.save(update_fields=['status'])
                mock_get.return_value.json.return_value = {
                    **provider_response,
                    'payment_status_description': 'Completed',
                }
                mock_get.return_value.raise_for_status.return_value = None

                response = self.client.get(
                    f'/api/orders/pesapal/ipn/?OrderTrackingId={self.payment.pesapal_order_tracking_id}'
                )

                self.assertEqual(response.status_code, 400)
                self.payment.refresh_from_db()
                self.assertEqual(self.payment.status, 'pending')

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
            'currency_code': 'UGX',
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
            'currency_code': 'UGX',
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
        self.assertEqual(AccountingRefund.objects.filter(order=self.order, status='completed').count(), 1)

        orders_response = self.client.get('/api/orders/admin/')
        order_codes = [order['code'] for order in orders_response.json()['results']]
        self.assertNotIn(self.order.code, order_codes)

        dashboard_response = self.client.get('/api/accounting/dashboard/')
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(dashboard_response.json()['total_refunds'], float(self.payment.amount))
        self.assertEqual(dashboard_response.json()['net_profit'], 0)

        duplicate_response = self.client.post(f'/api/orders/admin/returns/{self.return_request.id}/refunded/')

        self.assertEqual(duplicate_response.status_code, 400)
        mock_email.assert_called_once()
        self.assertEqual(AccountingRefund.objects.filter(order=self.order, status='completed').count(), 1)


class ProductRatingNotificationTests(TestCase):
    def test_delivered_order_prompts_product_review_not_service_rating(self):
        user = User.objects.create_user(email='product-rater@example.com', name='Product Rater', password='Password123!')
        product = Product.objects.create(name='Rating Phone', price=100000, stock=2)
        order = Order.objects.create(user=user, status='delivered', total=100000)
        OrderItem.objects.create(order=order, product=product, quantity=1, price=100000)

        with patch('users.emails.send_product_rating_email') as email_sender:
            from orders.tasks import send_product_rating_notifications
            send_product_rating_notifications(order.id)

        product_notification = Notification.objects.get(user=user, type='product_rating')
        self.assertIn(f'|{product.slug}?order_code={order.code}', product_notification.body)
        self.assertFalse(Notification.objects.filter(user=user, type='service_rating').exists())
        email_sender.assert_called_once()
