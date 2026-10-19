from datetime import timedelta
from unittest.mock import MagicMock, patch

from cloudinary import CloudinaryResource
from django.core.files.uploadedfile import SimpleUploadedFile
from cloudinary import CloudinaryResource
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from orders.models import Order, OrderItem
from products.models import Category, Product, ProductReview
from traders.models import TraderApplication, TraderFollower, TraderInventoryItem, TraderOrderItem, TraderProduct
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

	def test_admin_document_preview_sanitizes_storage_errors(self):
		url = reverse('admin-trader-document', args=[self.application.id, 'national-id'])
		with patch('traders.views.private_download_url', side_effect=OSError('Cloudinary unavailable')):
			with self.assertLogs('traders.views', level='ERROR'):
				response = self.client.get(url)

		self.assertEqual(response.status_code, 502)
		self.assertEqual(response.data['detail'], 'Could not retrieve the document from secure storage.')


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
