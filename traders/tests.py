from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from cloudinary import CloudinaryResource
from django.core.files.uploadedfile import SimpleUploadedFile
from cloudinary import CloudinaryResource
from django_redis.exceptions import ConnectionInterrupted
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from orders.models import Order, OrderItem, ReturnRequest
from products.models import Category, CategoryAttribute, Product, ProductReview
from settings_app.models import PlatformSettings
from traders.models import (
	TraderApplication, TraderEarning, TraderFollower, TraderInventoryItem,
	TraderOrderItem, TraderProduct, TraderWithdrawal,
)
from traders.wallet import record_paid_order_earnings, reverse_order_earnings, wallet_summary
from users.models import User


class PublicTraderProfileTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(email='buyer@example.com', name='Buyer', password='Password123!')
		self.trader = TraderApplication.objects.create(
			full_name='Seller Owner',
			email='seller@example.com',
			phone='0700000000',
			business_name='Majo Test Store',
			business_type='sole_proprietor',
			location='Kampala',
			district='Central',
			product_categories='Electronics',
			status='approved',
			user=User.objects.create_user(email='seller@example.com', name='Seller Owner', password='Password123!'),
		)
		self.category = Category.objects.create(name='Phones', slug='phones')
		self.product = Product.objects.create(
			name='Test Seller Phone', category=self.category, price=100000, stock=4, trader=self.trader,
		)
		self.delivered_order = Order.objects.create(user=self.user, status='delivered', total=100000)
		self.delivered_item = OrderItem.objects.create(
			order=self.delivered_order, product=self.product, quantity=1, price=100000,
		)
		self.cancelled_order = Order.objects.create(user=self.user, status='cancelled', total=100000)
		OrderItem.objects.create(order=self.cancelled_order, product=self.product, quantity=1, price=100000)
		self.ready_at = timezone.now()
		TraderOrderItem.objects.create(
			trader=self.trader, order_item=self.delivered_item, status='ready', ready_at=self.ready_at,
		)
		ProductReview.objects.create(
			product=self.product, order=self.delivered_order, order_item=self.delivered_item,
			user=self.user, overall_rating=4, product_quality_rating=3,
		)
		self.client = APIClient()

	def test_public_profile_returns_real_metrics_and_composite_score(self):
		response = self.client.get(reverse('trader-public-profile', args=[self.trader.uuid]))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['follower_count'], 0)
		self.assertEqual(response.data['customer_rating'], 4.0)
		self.assertEqual(response.data['quality_rating'], 3.0)
		self.assertEqual(response.data['shipping_speed_score'], 100.0)
		self.assertEqual(response.data['cancellation_rate'], 50.0)
		self.assertEqual(response.data['seller_score'], 72.5)
		self.assertFalse(response.data['is_following'])

	def test_product_response_exposes_approved_seller_uuid(self):
		response = self.client.get(reverse('product-detail-by-slug', args=[self.product.slug]))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['seller_uuid'], str(self.trader.uuid))

	def test_product_list_filter_returns_only_products_from_requested_seller(self):
		other_trader = TraderApplication.objects.create(
			full_name='Other Owner',
			email='other-seller@example.com',
			phone='0700000001',
			business_name='Other Store',
			business_type='sole_proprietor',
			location='Jinja',
			product_categories='Electronics',
			status='approved',
		)
		other_product = Product.objects.create(
			name='Other Seller Phone', category=self.category, price=100000, stock=2, trader=other_trader,
		)

		response = self.client.get(reverse('product-list'), {'seller': str(self.trader.uuid)})

		self.assertEqual(response.status_code, 200)
		product_ids = [item['id'] for item in response.data['results']]
		self.assertIn(self.product.id, product_ids)
		self.assertNotIn(other_product.id, product_ids)

	def test_following_is_authenticated_and_idempotent(self):
		url = reverse('trader-public-profile', args=[self.trader.uuid])
		preflight = self.client.options(url, HTTP_ORIGIN='https://www.majogadgets.com', HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST')
		self.assertEqual(preflight.status_code, 200)
		self.assertEqual(self.client.post(url).status_code, 401)

		self.client.force_authenticate(user=self.user)
		first = self.client.post(url)
		second = self.client.post(url)

		self.assertEqual(first.status_code, 201)
		self.assertEqual(second.status_code, 200)
		self.assertEqual(first.data['follower_count'], 1)
		self.assertEqual(TraderFollower.objects.filter(trader=self.trader, user=self.user).count(), 1)

		unfollow = self.client.delete(url)
		self.assertEqual(unfollow.status_code, 200)
		self.assertEqual(unfollow.data['follower_count'], 0)

	def test_profile_is_not_public_when_seller_is_not_approved_or_visible(self):
		self.trader.is_visible = False
		self.trader.save(update_fields=['is_visible'])

		response = self.client.get(reverse('trader-public-profile', args=[self.trader.uuid]))

		self.assertEqual(response.status_code, 404)

	def test_trader_me_returns_200_for_user_without_trader_application(self):
		user = User.objects.create_user(email='noapp@example.com', name='No Trader', password='Password123!')
		self.client.force_authenticate(user=user)

		response = self.client.get(reverse('trader-me'))

		self.assertEqual(response.status_code, 200)
		self.assertIsNone(response.data)


class TraderApplicationTermsTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(email='applicant@example.com', name='Applicant', password='Password123!')
		self.client = APIClient()
		self.client.force_authenticate(user=self.user)
		self.payload = {
			'full_name': 'Applicant',
			'email': self.user.email,
			'phone': '0700000000',
			'national_id': 'CM1234567890AB',
			'business_name': 'Applicant Gadgets',
			'business_type': 'sole_proprietor',
			'location': 'Kampala',
			'product_categories': 'Electronics',
		}

	def test_application_rejects_missing_terms_acceptance(self):
		response = self.client.post('/api/traders/apply/', self.payload, format='json')

		self.assertEqual(response.status_code, 400)
		self.assertIn('agreed_to_terms', response.data)

	@patch('cloudinary.models.uploader.upload_resource')
	def test_application_accepts_explicit_terms_agreement_and_evidence(self, mock_upload):
		mock_upload.return_value = CloudinaryResource(
			public_id='trader_applications/test-document',
			version='1',
			format='pdf',
			type='authenticated',
			resource_type='raw',
		)
		payload = {
			**self.payload,
			'agreed_to_terms': True,
			'national_id_document': SimpleUploadedFile('national-id.pdf', b'%PDF-id', content_type='application/pdf'),
			'ura_certificate_document': SimpleUploadedFile('ura-certificate.pdf', b'%PDF-ura', content_type='application/pdf'),
			'business_location_proof': SimpleUploadedFile('premises.pdf', b'%PDF-premises', content_type='application/pdf'),
		}
		response = self.client.post(
			'/api/traders/apply/',
			payload,
			format='multipart',
		)

		self.assertEqual(response.status_code, 201)
		self.assertTrue(response.data['agreed_to_terms'])

	@patch('cloudinary.models.uploader.upload_resource')
	def test_numeric_only_national_id_is_rejected(self, mock_upload):
		mock_upload.return_value = CloudinaryResource(
			public_id='trader_applications/test-document', version='1', format='pdf',
			type='authenticated', resource_type='raw',
		)
		payload = {
			**self.payload,
			'national_id': '123456789012',
			'agreed_to_terms': True,
			'national_id_document': SimpleUploadedFile('national-id.pdf', b'%PDF-id', content_type='application/pdf'),
			'business_location_proof': SimpleUploadedFile('premises.pdf', b'%PDF-premises', content_type='application/pdf'),
			'tin': '1234567890',
		}

		response = self.client.post('/api/traders/apply/', payload, format='multipart')

		self.assertEqual(response.status_code, 400)
		self.assertIn('national_id', response.data)


@override_settings(MAJO_BUSINESS_ADDRESS='Majo Gadgets, Kampala, Uganda')
class TraderApplicationApprovalTests(TestCase):
	def setUp(self):
		self.admin = User.objects.create_user(email='reviewer@example.com', name='Reviewer', password='Password123!', is_staff=True)
		self.client = APIClient()
		self.client.force_authenticate(user=self.admin)
		self.application = TraderApplication.objects.create(
			full_name='Applicant', email='approved-applicant@example.com', phone='0700000000',
			national_id='CM1234567890AB',
			national_id_document=CloudinaryResource(public_id='id-copy', version='1', format='pdf', type='authenticated', resource_type='raw'),
			business_name='Applicant Gadgets', business_type='sole_proprietor', business_reg_no='REG-123',
			tin='1234567890', location='Kampala',
			business_location_proof=CloudinaryResource(public_id='location-proof', version='1', format='pdf', type='authenticated', resource_type='raw'),
			product_categories='Electronics', agreed_to_terms=True,
		)

	@patch('users.emails.send_trader_agreement_email')
	def test_approval_requires_admin_document_verification_and_issues_agreement(self, _send_email):
		url = reverse('admin-trader-approve', args=[self.application.id])
		blocked = self.client.post(url, {}, format='json')
		self.assertEqual(blocked.status_code, 400)

		approved = self.client.post(url, {'documents_verified': True}, format='json')
		self.assertEqual(approved.status_code, 200)
		self.assertTrue(approved.data['documents_verified'])
		self.assertTrue(approved.data['agreement_reference'])
		self.assertIsNotNone(approved.data['agreement_issued_at'])
		self.assertTrue(approved.data['agreement_required'])
		self.assertEqual(approved.data['agreement_version'], '1.0')

	@patch('users.emails.send_trader_agreement_email')
	def test_unsigned_trader_cannot_access_portal_and_can_sign_by_name(self, _send_email):
		applicant = User.objects.create_user(email=self.application.email, name='Applicant', password='Password123!')
		self.application.user = applicant
		self.application.save(update_fields=['user'])
		self.client.post(reverse('admin-trader-approve', args=[self.application.id]), {'documents_verified': True}, format='json')

		agreement_url = reverse('trader-agreement', args=[self.application.uuid])
		self.client.force_authenticate(user=applicant)
		self.assertEqual(self.client.get(reverse('trader-profile', args=[self.application.uuid])).status_code, 404)
		self.assertEqual(self.client.get(agreement_url).status_code, 200)

		invalid_name = self.client.post(agreement_url, {'accepted': True, 'signed_name': 'Someone Else'}, format='json')
		self.assertEqual(invalid_name.status_code, 400)

		signed = self.client.post(agreement_url, {'accepted': True, 'signed_name': 'Applicant'}, format='json')
		self.assertEqual(signed.status_code, 200)
		self.assertFalse(signed.data['id_document_included'])
		self.assertEqual(signed.data['trader']['national_id'], 'CM1234567890AB')
		self.assertIsNotNone(signed.data['effective_at'])
		self.assertEqual(self.client.get(reverse('trader-profile', args=[self.application.uuid])).status_code, 200)
		self.assertEqual(self.client.post(agreement_url, {'accepted': True, 'signed_name': 'Applicant'}, format='json').status_code, 400)

	def test_admin_document_preview_downloads_authenticated_raw_file(self):
		url = reverse('admin-trader-document', args=[self.application.id, 'national-id'])
		upstream_response = MagicMock()
		upstream_response.read.return_value = b'%PDF-id-copy'
		upstream_response.headers.get.return_value = 'application/pdf'
		with patch('traders.views.private_download_url', return_value='https://cloudinary.test/private-download') as download_url:
			with patch('traders.views.urlopen') as open_url:
				open_url.return_value.__enter__.return_value = upstream_response
				response = self.client.get(url)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.content, b'%PDF-id-copy')
		self.assertEqual(response['Content-Type'], 'application/pdf')
		self.assertEqual(response['Cache-Control'], 'private, no-store')
		download_url.assert_called_once()
		self.assertEqual(download_url.call_args.args, ('id-copy', 'pdf'))
		self.assertEqual(download_url.call_args.kwargs['resource_type'], 'raw')
		self.assertEqual(download_url.call_args.kwargs['type'], 'authenticated')
		open_url.assert_called_once_with('https://cloudinary.test/private-download', timeout=20)

	def test_admin_document_preview_uses_stored_cloudinary_delivery_metadata(self):
		self.application.national_id_document = CloudinaryResource(
			public_id='legacy-id-copy',
			version='1',
			format='pdf',
			type='upload',
			resource_type='raw',
		)
		self.application.save(update_fields=['national_id_document'])
		upstream_response = MagicMock()
		upstream_response.read.return_value = b'%PDF-legacy-id-copy'
		upstream_response.headers.get.return_value = 'application/pdf'

		with patch('traders.views.private_download_url', return_value='https://cloudinary.test/download') as download_url:
			with patch('traders.views.urlopen') as open_url:
				open_url.return_value.__enter__.return_value = upstream_response
				response = self.client.get(reverse('admin-trader-document', args=[self.application.id, 'national-id']))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(download_url.call_args.kwargs['resource_type'], 'raw')
		self.assertEqual(download_url.call_args.kwargs['type'], 'upload')

	def test_admin_document_preview_falls_back_to_signed_delivery_url(self):
		url = reverse('admin-trader-document', args=[self.application.id, 'national-id'])
		upstream_response = MagicMock()
		upstream_response.read.return_value = b'%PDF-id-copy'
		upstream_response.headers.get.return_value = 'application/pdf'
		fallback_context = MagicMock()
		fallback_context.__enter__.return_value = upstream_response
		private_download_error = HTTPError(
			'https://cloudinary.test/private-download', 403, 'Forbidden', {}, None,
		)

		with patch('traders.views.private_download_url', return_value='https://cloudinary.test/private-download'):
			with patch('traders.views.cloudinary_url', return_value=('https://cloudinary.test/signed-delivery', {})) as signed_url:
				with patch('traders.views.urlopen', side_effect=[private_download_error, fallback_context]) as open_url:
					response = self.client.get(url)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.content, b'%PDF-id-copy')
		signed_url.assert_called_once_with(
			'id-copy',
			format='pdf',
			resource_type='raw',
			type='authenticated',
			version='1',
			sign_url=True,
			secure=True,
		)
		self.assertEqual(open_url.call_count, 2)

	def test_admin_document_preview_sanitizes_storage_errors(self):
		url = reverse('admin-trader-document', args=[self.application.id, 'national-id'])
		with patch('traders.views.private_download_url', side_effect=OSError('Cloudinary unavailable')):
			with patch('traders.views.cloudinary_url', return_value=('https://cloudinary.test/signed-delivery', {})):
				with patch('traders.views.urlopen', side_effect=OSError('Cloudinary unavailable')):
					with self.assertLogs('traders.views', level='ERROR') as logs:
						response = self.client.get(url)

		self.assertEqual(response.status_code, 502)
		self.assertEqual(response.data['detail'], 'Could not retrieve the document from secure storage.')
		self.assertNotIn('cloudinary.test', '\n'.join(logs.output))


class TraderInventoryStockSyncTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(email='inventory-seller@example.com', name='Inventory Seller', password='Password123!')
		self.trader = TraderApplication.objects.create(
			full_name='Inventory Seller',
			email=self.user.email,
			phone='0700000000',
			business_name='Inventory Test Store',
			business_type='sole_proprietor',
			location='Kampala',
			product_categories='Electronics',
			status='approved',
			user=self.user,
		)
		self.product = TraderProduct.objects.create(
			trader=self.trader,
			name='Test Inventory Product',
			price=25000,
			stock=0,
		)
		self.client = APIClient()
		self.client.force_authenticate(user=self.user)

	def test_shop_visibility_hides_and_restores_products_without_overwriting_product_state(self):
		public_product = Product.objects.create(
			name='Visibility Test Product',
			price=25000,
			stock=4,
			is_active=True,
			review_status='approved',
			trader=self.trader,
		)
		account_url = reverse('trader-account', args=[self.trader.uuid])

		hidden = self.client.patch(account_url, {'is_visible': False}, format='json')
		public_list = APIClient().get(reverse('product-list'))
		public_product.refresh_from_db()
		self.assertEqual(hidden.status_code, 200)
		self.assertNotIn(public_product.id, [item['id'] for item in public_list.data['results']])
		self.assertTrue(public_product.is_active)

		visible = self.client.patch(account_url, {'is_visible': True}, format='json')
		public_list = APIClient().get(reverse('product-list'))
		public_product.refresh_from_db()
		self.assertEqual(visible.status_code, 200)
		self.assertIn(public_product.id, [item['id'] for item in public_list.data['results']])
		self.assertTrue(public_product.is_active)

		closed = self.client.patch(account_url, {'is_closed': True}, format='json')
		public_list = APIClient().get(reverse('product-list'))
		public_product.refresh_from_db()
		self.assertEqual(closed.status_code, 200)
		self.assertNotIn(public_product.id, [item['id'] for item in public_list.data['results']])
		self.assertTrue(public_product.is_active)

		reopened = self.client.patch(account_url, {'is_closed': False}, format='json')
		public_list = APIClient().get(reverse('product-list'))
		self.assertEqual(reopened.status_code, 200)
		self.assertIn(public_product.id, [item['id'] for item in public_list.data['results']])

	def test_reopening_shop_restores_products_disabled_by_previous_visibility_sync(self):
		public_product = Product.objects.create(
			name='Previously Hidden Product',
			price=25000,
			stock=4,
			is_active=False,
			review_status='approved',
			trader=self.trader,
		)
		trader_product = TraderProduct.objects.create(
			trader=self.trader,
			name='Previously Hidden Product',
			price=25000,
			stock=4,
			is_active=True,
		)
		public_product.trader_product = trader_product
		public_product.save(update_fields=['trader_product'])
		account_url = reverse('trader-account', args=[self.trader.uuid])

		response = self.client.patch(account_url, {'is_visible': True}, format='json')
		public_list = APIClient().get(reverse('product-list'))
		public_product.refresh_from_db()

		self.assertEqual(response.status_code, 200)
		self.assertTrue(public_product.is_active)
		self.assertIn(public_product.id, [item['id'] for item in public_list.data['results']])

	def test_new_trader_product_and_variants_wait_for_admin_approval(self):
		category = Category.objects.create(name='Color Goods', slug='color-goods')
		CategoryAttribute.objects.create(
			category=category, name='Color', key='color', input_type='color', is_variant=True,
		)
		response = self.client.post(
			reverse('trader-products', args=[self.trader.uuid]),
			{
				'name': 'Colorful Gadget',
				'price': '1000.00',
				'stock': 3,
				'category_id': category.pk,
				'variants': [{
					'sku': 'COLOR-GADGET-BLACK',
					'options': {'color': 'Black'},
					'price': '1200.00',
					'stock': 2,
				}],
				'submit_for_review': True,
			},
			format='json',
		)

		self.assertEqual(response.status_code, 201, response.data)
		self.assertEqual(response.data['review_status'], 'pending_review')
		trader_product = TraderProduct.objects.get(uuid=response.data['uuid'])
		public_product = Product.objects.get(trader_product=trader_product)
		self.assertFalse(public_product.is_active)
		self.assertEqual(public_product.review_status, 'pending_review')
		self.assertEqual(public_product.stock, 2)
		self.assertEqual(public_product.variants.count(), 1)
		public_list = APIClient().get(reverse('product-list'))
		self.assertNotIn(public_product.pk, [item['id'] for item in public_list.data['results']])

	def test_adding_inventory_quantity_updates_product_stock(self):
		response = self.client.post(
			reverse('trader-inventory', args=[self.trader.uuid]),
			{'product': self.product.id, 'quantity': 12, 'cost_price': 15000},
			format='json',
		)

		self.assertEqual(response.status_code, 201)
		self.product.refresh_from_db()
		inventory_item = TraderInventoryItem.objects.get(trader=self.trader, product=self.product)
		self.assertEqual(inventory_item.quantity, 12)
		self.assertEqual(self.product.stock, 12)
		self.assertEqual(response.data['product_stock'], 12)

	def test_stock_movement_updates_linked_public_product_stock(self):
		public_product = Product.objects.create(
			name=self.product.name,
			price=self.product.price,
			stock=0,
			trader=self.trader,
			trader_product=self.product,
		)
		item = TraderInventoryItem.objects.create(
			trader=self.trader, product=self.product, quantity=0, cost_price=15000,
		)

		response = self.client.post(
			reverse('trader-stock-movement', args=[self.trader.uuid, item.id]),
			{'type': 'in', 'quantity': 12},
			format='json',
		)

		self.assertEqual(response.status_code, 200)
		self.product.refresh_from_db()
		public_product.refresh_from_db()
		self.assertEqual(response.data['quantity'], 12)
		self.assertEqual(self.product.stock, 12)
		self.assertEqual(public_product.stock, 12)

	def test_stock_movement_reuses_matching_legacy_public_product(self):
		public_product = Product.objects.create(
			name=self.product.name,
			price=self.product.price,
			stock=0,
			trader=self.trader,
		)
		original_slug = public_product.slug
		item = TraderInventoryItem.objects.create(
			trader=self.trader, product=self.product, quantity=0, cost_price=15000,
		)

		response = self.client.post(
			reverse('trader-stock-movement', args=[self.trader.uuid, item.id]),
			{'type': 'in', 'quantity': 12},
			format='json',
		)

		self.assertEqual(response.status_code, 200)
		public_product.refresh_from_db()
		self.assertEqual(public_product.trader_product, self.product)
		self.assertEqual(public_product.stock, 12)
		self.assertEqual(public_product.slug, original_slug)
		self.assertEqual(
			Product.objects.filter(trader=self.trader, name__iexact=self.product.name).count(),
			1,
		)
		public_response = self.client.get(reverse('product-detail', args=[public_product.id]))
		self.assertEqual(public_response.status_code, 200)
		self.assertEqual(public_response.data['stock'], 12)

	def test_stock_movement_links_unowned_product_when_name_and_trader_image_match(self):
		self.product.image = 'trader_products/soldering-iron.jpg'
		self.product.save(update_fields=['image'])
		public_product = Product.objects.create(
			name=self.product.name,
			price=self.product.price,
			stock=0,
			image='trader_products/soldering-iron.jpg',
		)
		self.product.refresh_from_db()
		public_product.refresh_from_db()
		self.assertEqual(str(self.product.image), str(public_product.image))
		self.assertEqual(public_product.name.lower(), self.product.name.lower())
		item = TraderInventoryItem.objects.create(
			trader=self.trader, product=self.product, quantity=0, cost_price=15000,
		)

		response = self.client.post(
			reverse('trader-stock-movement', args=[self.trader.uuid, item.id]),
			{'type': 'in', 'quantity': 12},
			format='json',
		)

		self.assertEqual(response.status_code, 200)
		public_product.refresh_from_db()
		self.assertEqual(public_product.trader_product, self.product)
		self.assertEqual(public_product.stock, 12)

	def test_trader_products_expose_the_linked_public_product_id(self):
		public_product = Product.objects.create(
			name='Public Inventory Product',
			price=25000,
			stock=8,
			trader=self.trader,
			trader_product=self.product,
		)

		response = self.client.get(reverse('trader-products', args=[self.trader.uuid]))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data[0]['public_product_id'], public_product.id)

	def test_linked_trader_user_can_fetch_profile_and_products_when_emails_differ(self):
		self.trader.email = 'legacy-trader-email@example.com'
		self.trader.save(update_fields=['email'])

		profile_response = self.client.get(reverse('trader-profile', args=[self.trader.uuid]))
		products_response = self.client.get(reverse('trader-products', args=[self.trader.uuid]))

		self.assertEqual(profile_response.status_code, 200)
		self.assertEqual(products_response.status_code, 200)
		self.assertEqual([item['uuid'] for item in products_response.data], [str(self.product.uuid)])

	def test_trader_can_edit_own_product_details_and_public_product_stays_in_sync(self):
		public_product = Product.objects.create(
			name=self.product.name,
			price=self.product.price,
			stock=self.product.stock,
			trader=self.trader,
			trader_product=self.product,
		)

		response = self.client.patch(
			reverse('trader-product-detail', args=[self.trader.uuid, self.product.uuid]),
			{'name': 'Updated Inventory Product', 'price': '30000.00', 'stock': '6',
			 'short_description': 'Updated product details', 'is_active': 'true',
			 'is_featured': 'false', 'is_new_deal': 'false'},
			format='multipart',
		)

		self.assertEqual(response.status_code, 200)
		self.product.refresh_from_db()
		public_product.refresh_from_db()
		self.assertEqual(self.product.name, 'Updated Inventory Product')
		self.assertEqual(self.product.price, Decimal('30000.00'))
		self.assertEqual(self.product.stock, 6)
		self.assertEqual(self.product.short_description, 'Updated product details')
		self.assertEqual(public_product.name, self.product.name)
		self.assertEqual(public_product.price, self.product.price)
		self.assertEqual(public_product.stock, self.product.stock)
		self.assertEqual(public_product.short_description, self.product.short_description)

	def test_renaming_product_updates_unique_public_row_with_same_image(self):
		self.product.image = 'trader_products/shared-product-image.jpg'
		self.product.save(update_fields=['image'])
		public_product = Product.objects.create(
			name='Old product name',
			price=self.product.price,
			stock=0,
			trader=self.trader,
			image='trader_products/shared-product-image.jpg',
		)
		self.product.refresh_from_db()
		public_product.refresh_from_db()
		self.assertEqual(str(self.product.image), str(public_product.image))

		response = self.client.patch(
			reverse('trader-product-detail', args=[self.trader.uuid, self.product.uuid]),
			{'name': 'New product name', 'price': '30000.00', 'stock': '6',
			 'is_active': 'true', 'is_featured': 'false', 'is_new_deal': 'false'},
			format='multipart',
		)

		self.assertEqual(response.status_code, 200)
		public_product.refresh_from_db()
		self.assertEqual(public_product.trader_product_id, self.product.pk)
		self.assertEqual(public_product.name, 'New Product Name')
		self.assertEqual(public_product.stock, 6)
		self.assertEqual(
			Product.objects.filter(trader=self.trader).count(),
			1,
		)

	def test_delete_deactivates_unique_public_row_even_when_name_changed(self):
		self.product.image = 'trader_products/shared-product-image.jpg'
		self.product.save(update_fields=['image'])
		public_product = Product.objects.create(
			name='Old product name',
			price=self.product.price,
			stock=0,
			trader=self.trader,
			image='trader_products/shared-product-image.jpg',
		)
		self.product.refresh_from_db()
		public_product.refresh_from_db()

		response = self.client.delete(
			reverse('trader-product-detail', args=[self.trader.uuid, self.product.uuid]),
		)

		self.assertEqual(response.status_code, 204)
		public_product.refresh_from_db()
		self.assertFalse(public_product.is_active)

	def test_trader_can_update_and_clear_product_category_and_optional_fields(self):
		category = Category.objects.create(name='Tools', slug='tools')
		response = self.client.patch(
			reverse('trader-product-detail', args=[self.trader.uuid, self.product.uuid]),
			{'name': 'Updated Product', 'price': '30000.00', 'stock': '6',
			 'category_id': str(category.pk), 'original_price': '45000.00',
			 'short_description': 'Updated details', 'long_description': 'Long details',
			 'is_active': 'true', 'is_featured': 'false', 'is_new_deal': 'false'},
			format='multipart',
		)

		self.assertEqual(response.status_code, 200)
		self.product.refresh_from_db()
		self.assertEqual(self.product.category, category)
		self.assertEqual(response.data['category_id'], category.pk)

		response = self.client.patch(
			reverse('trader-product-detail', args=[self.trader.uuid, self.product.uuid]),
			{'category_id': '', 'original_price': '', 'short_description': '',
			 'long_description': '', 'is_active': 'true', 'is_featured': 'false',
			 'is_new_deal': 'false'},
			format='multipart',
		)

		self.assertEqual(response.status_code, 200)
		self.product.refresh_from_db()
		self.assertIsNone(self.product.category)
		self.assertIsNone(self.product.original_price)
		self.assertEqual(self.product.short_description, '')
		self.assertEqual(self.product.long_description, '')
		self.assertIsNone(response.data['category_id'])

	@patch('django.core.cache.cache.delete', side_effect=ConnectionInterrupted(connection=None))
	def test_trader_can_delete_product_when_cache_is_unavailable(self, _delete_cache):
		public_product = Product.objects.create(
			name=self.product.name,
			price=self.product.price,
			stock=self.product.stock,
			trader=self.trader,
			trader_product=self.product,
		)

		with self.assertLogs('traders.views', level='ERROR'):
			response = self.client.delete(
				reverse('trader-product-detail', args=[self.trader.uuid, self.product.uuid]),
			)

		self.assertEqual(response.status_code, 204)
		self.assertFalse(TraderProduct.objects.filter(pk=self.product.pk).exists())
		public_product.refresh_from_db()
		self.assertFalse(public_product.is_active)
		self.assertIsNone(public_product.trader_product_id)

	def test_trader_can_delete_matching_unlinked_public_product(self):
		public_product = Product.objects.create(
			name=self.product.name,
			price=self.product.price,
			stock=self.product.stock,
			trader=self.trader,
		)

		response = self.client.delete(
			reverse('trader-product-detail', args=[self.trader.uuid, self.product.uuid]),
		)

		self.assertEqual(response.status_code, 204)
		public_product.refresh_from_db()
		self.assertFalse(public_product.is_active)
		self.assertIsNone(public_product.trader_product_id)

	@patch('django.core.cache.cache.delete', side_effect=ConnectionInterrupted(connection=None))
	def test_product_update_succeeds_when_cache_invalidation_fails(self, _delete_cache):
		public_product = Product.objects.create(
			name=self.product.name,
			price=self.product.price,
			stock=self.product.stock,
			trader=self.trader,
			trader_product=self.product,
		)

		with self.assertLogs('traders.views', level='ERROR'):
			response = self.client.patch(
				reverse('trader-product-detail', args=[self.trader.uuid, self.product.uuid]),
				{'name': 'Updated Despite Cache Failure', 'price': '30000.00', 'stock': '6',
				 'is_active': 'true', 'is_featured': 'false', 'is_new_deal': 'false'},
				format='multipart',
			)

		self.assertEqual(response.status_code, 200)
		self.product.refresh_from_db()
		public_product.refresh_from_db()
		self.assertEqual(self.product.stock, 6)
		self.assertEqual(public_product.stock, 6)


class TraderWalletTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			email='wallet-seller@example.com', name='Wallet Seller', password='Password123!',
		)
		self.trader = TraderApplication.objects.create(
			full_name='Wallet Seller',
			email=self.user.email,
			phone='0700000000',
			business_name='Wallet Test Store',
			business_type='sole_proprietor',
			location='Kampala',
			product_categories='Electronics',
			status='approved',
			user=self.user,
			payout_method='mobile_money',
			payout_provider='MTN',
			payout_account_name='Wallet Seller',
			payout_account_number='256700000000',
		)
		self.product = Product.objects.create(
			name='Wallet Product', price='12000.00', stock=2, trader=self.trader,
		)
		self.order = Order.objects.create(user=self.user, status='processing', total='26400.00')
		self.item = OrderItem.objects.create(
			order=self.order,
			product=self.product,
			quantity=2,
			price='13200.00',
			seller_price='12000.00',
			platform_commission_pct='10.00',
			platform_commission='2400.00',
		)
		self.client = APIClient()

	def test_paid_order_earnings_use_listed_price_and_remain_locked_for_five_days(self):
		record_paid_order_earnings(self.order)

		earning = TraderEarning.objects.get(order_item=self.item)
		summary = wallet_summary(self.trader)
		self.assertEqual(earning.seller_amount, Decimal('24000.00'))
		self.assertEqual(earning.commission_amount, Decimal('2400.00'))
		self.assertEqual(summary['locked_balance'], Decimal('24000.00'))
		self.assertEqual(summary['available_balance'], Decimal('0.00'))
		self.assertAlmostEqual(
			(earning.available_at - timezone.now()).total_seconds(),
			5 * 24 * 60 * 60,
			delta=5,
		)
		record_paid_order_earnings(self.order)
		self.assertEqual(TraderEarning.objects.filter(order_item=self.item).count(), 1)

	def test_withdrawal_reserves_matured_balance_and_admin_records_transfer(self):
		PlatformSettings.objects.create(pk=1, withdrawal_minimum='1000.00', withdrawal_fee='100.00')
		record_paid_order_earnings(self.order)
		TraderEarning.objects.filter(order_item=self.item).update(available_at=timezone.now() - timedelta(seconds=1))
		self.client.force_authenticate(user=self.user)
		url = reverse('trader-wallet', args=[self.trader.uuid])

		response = self.client.post(url, {'amount': '5000.00'}, format='json')

		self.assertEqual(response.status_code, 201, response.data)
		withdrawal = TraderWithdrawal.objects.get()
		self.assertEqual(withdrawal.payout_amount, Decimal('4900.00'))
		self.assertEqual(wallet_summary(self.trader)['available_balance'], Decimal('19000.00'))

		admin = User.objects.create_user(
			email='wallet-admin@example.com', name='Wallet Admin',
			password='Password123!', is_staff=True,
		)
		self.client.force_authenticate(user=admin)
		admin_response = self.client.post(
			reverse('admin-trader-withdrawal-update', args=[withdrawal.pk]),
			{'status': 'paid', 'transfer_reference': 'BANK-TRANSFER-1'},
			format='json',
		)
		self.assertEqual(admin_response.status_code, 200)
		withdrawal.refresh_from_db()
		self.assertEqual(withdrawal.status, 'paid')
		self.assertEqual(withdrawal.transfer_reference, 'BANK-TRANSFER-1')

	def test_unsigned_trader_cannot_request_withdrawal(self):
		self.trader.agreement_required = True
		self.trader.save(update_fields=['agreement_required'])
		self.client.force_authenticate(user=self.user)

		response = self.client.post(
			reverse('trader-wallet', args=[self.trader.uuid]),
			{'amount': '5000.00'},
			format='json',
		)

		self.assertEqual(response.status_code, 404)
		self.assertEqual(TraderWithdrawal.objects.count(), 0)

	def test_return_request_blocks_trader_earnings_until_rejected_or_refunded(self):
		record_paid_order_earnings(self.order)
		TraderEarning.objects.filter(order_item=self.item).update(
			available_at=timezone.now() - timedelta(seconds=1),
		)
		return_request = ReturnRequest.objects.create(
			order=self.order,
			reason='Product returned by customer',
			status='pending',
		)

		summary = wallet_summary(self.trader)
		self.assertEqual(summary['total_earned'], Decimal('0.00'))
		self.assertEqual(summary['locked_balance'], Decimal('0.00'))
		self.assertEqual(summary['available_balance'], Decimal('0.00'))

		return_request.status = 'rejected'
		return_request.save(update_fields=['status'])
		self.assertEqual(wallet_summary(self.trader)['available_balance'], Decimal('24000.00'))

		return_request.status = 'refunded'
		return_request.save(update_fields=['status'])
		reverse_order_earnings(self.order)
		self.assertEqual(wallet_summary(self.trader)['total_earned'], Decimal('0.00'))

	def test_wallet_earnings_include_return_status_for_payment_activity(self):
		record_paid_order_earnings(self.order)
		ReturnRequest.objects.create(order=self.order, reason='Return requested', status='pending')
		self.client.force_authenticate(user=self.user)

		response = self.client.get(reverse('trader-wallet', args=[self.trader.uuid]))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['earnings'][0]['return_request_status'], 'pending')
