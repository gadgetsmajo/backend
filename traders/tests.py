from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from orders.models import Order, OrderItem
from products.models import Category, Product, ProductReview
from traders.models import TraderApplication, TraderFollower, TraderOrderItem
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
