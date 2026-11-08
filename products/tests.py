from django.contrib.auth import get_user_model
from django_redis.exceptions import ConnectionInterrupted
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
from rest_framework.test import APIClient

from orders.models import Order, OrderItem
from products.models import Category, FlashSale, Product, ProductReview
from settings_app.models import PlatformSettings
from traders.models import TraderApplication, TraderProduct

User = get_user_model()


class ProductRecommendationsAPITest(TestCase):
    def setUp(self):
        self.phone_category = Category.objects.create(name='Phones', slug='phones')
        self.audio_category = Category.objects.create(name='Audio', slug='audio')

        self.purchased_product = Product.objects.create(
            name='Smartphone X', category=self.phone_category, price=550000, original_price=650000,
            stock=10, rating=4.9, is_active=True,
        )
        self.related_product = Product.objects.create(
            name='Smartphone Y', category=self.phone_category, price=600000, original_price=700000,
            stock=10, rating=4.8, is_active=True,
        )
        self.other_product = Product.objects.create(
            name='Bluetooth Speaker', category=self.audio_category, price=250000, original_price=300000,
            stock=5, rating=4.7, is_active=True,
        )

        self.user = User.objects.create_user(email='buyer@example.com', password='strong-pass-123', name='Buyer')
        self.order = Order.objects.create(
            user=self.user,
            subtotal=550000,
            total=550000,
            delivery_address='Test address',
            phone='0770000000',
        )
        OrderItem.objects.create(order=self.order, product=self.purchased_product, quantity=1, price=self.purchased_product.price)

    def test_authenticated_user_gets_category_based_recommendations(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('product-recommendations'))

        self.assertEqual(response.status_code, 200)
        product_ids = [item['id'] for item in response.data]
        self.assertIn(self.related_product.id, product_ids)
        self.assertNotIn(self.other_product.id, product_ids[:3])

    def test_guest_user_gets_fallback_products(self):
        response = self.client.get(reverse('product-recommendations'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.data) >= 1)
        self.assertIn(self.purchased_product.id, [item['id'] for item in response.data])

    def test_top_bought_products_rank_by_delivered_quantity_and_omit_unsold(self):
        self.order.status = 'delivered'
        self.order.save(update_fields=['status'])
        OrderItem.objects.create(
            order=self.order, product=self.purchased_product, quantity=2, price=self.purchased_product.price,
        )
        second_order = Order.objects.create(
            user=self.user, status='delivered', subtotal=600000, total=600000,
        )
        OrderItem.objects.create(
            order=second_order, product=self.related_product, quantity=1, price=self.related_product.price,
        )

        response = self.client.get(reverse('product-list'), {'top_bought': 'true'})

        self.assertEqual(response.status_code, 200)
        product_ids = [item['id'] for item in response.data['results']]
        self.assertEqual(product_ids[:2], [self.purchased_product.id, self.related_product.id])
        self.assertNotIn(self.other_product.id, product_ids)


    def test_product_list_honors_page_size_and_returns_next_page(self):
        for index in range(3):
            Product.objects.create(
                name=f'Extra Product {index}',
                category=self.phone_category,
                price=10000,
                stock=1,
            )

        first_page = self.client.get(reverse('product-list'), {'page_size': 2})
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(len(first_page.data['results']), 2)
        self.assertIsNotNone(first_page.data['next'])

        second_page = self.client.get(reverse('product-list'), {'page': 2, 'page_size': 2})
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data['results']), 2)

    def test_inactive_products_are_hidden_from_public_catalog_but_visible_to_staff(self):
        client = APIClient()
        inactive_product = Product.objects.create(
            name='Inactive Product',
            slug='inactive-product',
            category=self.phone_category,
            price=10000,
            stock=5,
            is_active=False,
        )

        public_list = client.get(reverse('product-list'))
        public_detail = client.get(
            reverse('product-detail-by-slug', kwargs={'slug': inactive_product.slug})
        )

        self.assertEqual(public_list.status_code, 200)
        self.assertNotIn(inactive_product.id, [item['id'] for item in public_list.data['results']])
        self.assertEqual(public_detail.status_code, 404)

        staff = User.objects.create_user(
            email='catalog-admin@example.com',
            password='strong-pass-123',
            name='Catalog Admin',
            is_staff=True,
        )
        client.force_authenticate(user=staff)

        staff_list = client.get(reverse('product-list'))
        staff_detail = client.get(
            reverse('product-detail-by-slug', kwargs={'slug': inactive_product.slug})
        )

        self.assertEqual(staff_list.status_code, 200)
        self.assertIn(inactive_product.id, [item['id'] for item in staff_list.data['results']])
        self.assertEqual(staff_detail.status_code, 200)


class ProductCommissionPricingAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name='Accessories', slug='accessories')
        self.existing_product = Product.objects.create(
            name='Existing Product',
            category=self.category,
            price='100.00',
            stock=5,
        )

    def test_current_commission_applies_to_products_added_before_and_after_setting(self):
        list_before_setting = self.client.get(reverse('product-list'))
        detail_before_setting = self.client.get(
            reverse('product-detail', args=[self.existing_product.id])
        )
        self.assertEqual(list_before_setting.data['results'][0]['price'], '100.00')
        self.assertEqual(list_before_setting.data['results'][0]['listed_price'], '100.00')
        self.assertEqual(detail_before_setting.data['price'], '100.00')
        self.assertEqual(detail_before_setting.data['listed_price'], '100.00')

        settings = PlatformSettings.get()
        settings.commission = '10.00'
        settings.save()
        new_product = Product.objects.create(
            name='New Product',
            category=self.category,
            price='200.00',
            stock=5,
        )

        response = self.client.get(reverse('product-list'))

        self.assertEqual(response.status_code, 200)
        prices = {item['id']: item['price'] for item in response.data['results']}
        self.assertEqual(prices[self.existing_product.id], '110.00')
        self.assertEqual(prices[new_product.id], '220.00')
        self.assertEqual(
            next(item for item in response.data['results'] if item['id'] == self.existing_product.id)['listed_price'],
            '100.00',
        )
        detail_after_setting = self.client.get(
            reverse('product-detail', args=[self.existing_product.id])
        )
        self.assertEqual(detail_after_setting.data['price'], '110.00')
        self.existing_product.refresh_from_db()
        self.assertEqual(self.existing_product.price, 100)

    def test_admin_edits_sync_linked_trader_product_and_keep_listed_price(self):
        trader_user = User.objects.create_user(email='seller@example.com', name='Seller', password='Password123!')
        trader = TraderApplication.objects.create(
            full_name='Seller', email='seller@example.com', phone='0700000000',
            business_name='Seller Store', business_type='sole_proprietor',
            location='Kampala', district='Central', product_categories='Phones',
            status='approved', user=trader_user,
        )
        trader_product = TraderProduct.objects.create(
            trader=trader, name='Original Product', price='100.00',
            short_description='Old details', stock=2,
        )
        product = Product.objects.create(
            name='Original Product', category=self.category, price='100.00', stock=2,
            trader=trader, trader_product=trader_product,
        )
        settings = PlatformSettings.get()
        settings.commission = '10.00'
        settings.save()
        admin = User.objects.create_user(email='admin@example.com', name='Admin', password='Password123!', is_staff=True)
        self.client.force_authenticate(user=admin)

        response = self.client.patch(reverse('product-detail', args=[product.id]), {
            'name': 'Updated Product',
            'price': '150.00',
            'stock': 7,
            'short_description': 'Updated details',
            'category_id': '',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        trader_product.refresh_from_db()
        self.assertEqual(product.price, 150)
        self.assertEqual(product.category, None)
        self.assertEqual(trader_product.name, 'Updated Product')
        self.assertEqual(trader_product.price, 150)
        self.assertEqual(trader_product.stock, 7)
        self.assertEqual(trader_product.short_description, 'Updated details')
        self.assertIsNone(trader_product.category)
        self.assertEqual(response.data['price'], '165.00')
        self.assertEqual(response.data['listed_price'], '150.00')

    def test_non_admin_cannot_edit_product(self):
        user = User.objects.create_user(email='buyer@example.com', name='Buyer', password='Password123!')
        self.client.force_authenticate(user=user)

        response = self.client.patch(
            reverse('product-detail', args=[self.existing_product.id]),
            {'name': 'Unauthorized Change'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.existing_product.refresh_from_db()
        self.assertEqual(self.existing_product.name, 'Existing Product')

    @patch('django.core.cache.cache.delete', side_effect=ConnectionInterrupted(connection=None))
    def test_admin_can_update_product_when_cache_is_unavailable(self, _delete_cache):
        admin = User.objects.create_user(
            email='cache-admin@example.com',
            name='Cache Admin',
            password='Password123!',
            is_staff=True,
        )
        self.client.force_authenticate(user=admin)

        with self.assertLogs('products.views', level='ERROR'):
            response = self.client.patch(
                reverse('product-detail', args=[self.existing_product.id]),
                {'name': 'Updated During Cache Outage', 'price': '125.00'},
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        self.existing_product.refresh_from_db()
        self.assertEqual(self.existing_product.name, 'Updated During Cache Outage')
        self.assertEqual(self.existing_product.price, 125)

    @patch('django.core.cache.cache.delete', side_effect=ConnectionInterrupted(connection=None))
    def test_admin_can_delete_product_when_cache_is_unavailable(self, _delete_cache):
        admin = User.objects.create_user(
            email='cache-admin@example.com',
            name='Cache Admin',
            password='Password123!',
            is_staff=True,
        )
        self.client.force_authenticate(user=admin)

        with self.assertLogs('products.views', level='ERROR'):
            response = self.client.delete(
                reverse('product-detail', args=[self.existing_product.id]),
            )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Product.objects.filter(pk=self.existing_product.id).exists())


class FlashSalePermissionAPITest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Phones', slug='phones')
        self.trader_user = User.objects.create_user(email='trader@example.com', password='strong-pass-123', name='Trader')
        self.trader = TraderApplication.objects.create(
            full_name='Trader User',
            email='trader@example.com',
            phone='0700000000',
            business_name='Trader Store',
            business_type='sole_proprietor',
            location='Kampala',
            district='Central',
            product_categories='Phones',
            status='approved',
            user=self.trader_user,
        )
        self.product = Product.objects.create(
            name='Flash Product',
            category=self.category,
            price=100000,
            original_price=120000,
            stock=10,
            trader=self.trader,
            is_active=True,
        )
        self.admin = User.objects.create_user(email='admin@example.com', password='strong-pass-123', name='Admin', is_staff=True)
        self.client = APIClient()

    def test_trader_can_create_flash_sale_for_own_product(self):
        self.client.force_authenticate(user=self.trader_user)
        response = self.client.post(reverse('flash-sale-list'), {
            'product_id': self.product.id,
            'flash_price': '90000',
            'ends_at': '2099-01-01T12:00:00Z',
            'stock_limit': 5,
            'is_active': True,
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['product']['id'], self.product.id)

    def test_superadmin_cannot_create_flash_sale_for_trader_product(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reverse('flash-sale-list'), {
            'product_id': self.product.id,
            'flash_price': '90000',
            'ends_at': '2099-01-01T12:00:00Z',
            'stock_limit': 5,
            'is_active': True,
        }, format='json')

        self.assertEqual(response.status_code, 403)
        self.assertIn('detail', response.data)

    def test_trader_flash_sale_list_only_returns_their_sales_even_after_public_cache(self):
        other_user = User.objects.create_user(email='other-trader@example.com', password='strong-pass-123', name='Other Trader')
        other_trader = TraderApplication.objects.create(
            full_name='Other Trader',
            email=other_user.email,
            phone='0700000001',
            business_name='Other Trader Store',
            business_type='sole_proprietor',
            location='Jinja',
            district='Eastern',
            product_categories='Phones',
            status='approved',
            user=other_user,
        )
        other_product = Product.objects.create(
            name='Other Flash Product',
            category=self.category,
            price=120000,
            stock=6,
            trader=other_trader,
        )
        own_sale = FlashSale.objects.create(
            product=self.product,
            flash_price=90000,
            ends_at='2099-01-01T12:00:00Z',
            stock_limit=5,
        )
        FlashSale.objects.create(
            product=other_product,
            flash_price=110000,
            ends_at='2099-01-01T12:00:00Z',
            stock_limit=3,
        )

        public_response = self.client.get(reverse('flash-sale-list'))
        self.assertEqual(public_response.status_code, 200)

        self.client.force_authenticate(user=self.trader_user)
        trader_response = self.client.get(reverse('flash-sale-list'))

        self.assertEqual(trader_response.status_code, 200)
        sales = trader_response.data.get('results', trader_response.data) if isinstance(trader_response.data, dict) else trader_response.data
        self.assertEqual([sale['id'] for sale in sales], [own_sale.id])


class ProductReviewEligibilityAPITest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Phones', slug='phones')
        self.product = Product.objects.create(name='Reviewable Phone', category=self.category, price=100000, stock=5)
        self.user = User.objects.create_user(email='reviewer@example.com', password='strong-pass-123', name='Reviewer')
        self.reviewed_order = Order.objects.create(user=self.user, status='delivered', subtotal=100000, total=100000)
        self.reviewed_item = OrderItem.objects.create(order=self.reviewed_order, product=self.product, quantity=1, price=100000)
        self.unreviewed_order = Order.objects.create(user=self.user, status='delivered', subtotal=100000, total=100000)
        self.unreviewed_item = OrderItem.objects.create(order=self.unreviewed_order, product=self.product, quantity=1, price=100000)
        ProductReview.objects.create(
            product=self.product,
            order=self.reviewed_order,
            order_item=self.reviewed_item,
            user=self.user,
            overall_rating=5,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_eligibility_uses_requested_order_for_repeat_product_purchases(self):
        response = self.client.get(
            reverse('product-reviews-eligibility', args=[self.product.slug]),
            {'order_code': self.unreviewed_order.code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['eligible'])
        self.assertEqual(response.data['order_id'], self.unreviewed_order.id)
        self.assertEqual(response.data['order_item_id'], self.unreviewed_item.id)

    def test_reviewed_requested_order_is_not_eligible(self):
        response = self.client.get(
            reverse('product-reviews-eligibility', args=[self.product.slug]),
            {'order_code': self.reviewed_order.code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['eligible'])
        self.assertEqual(response.data['reason'], 'already_reviewed')

    def test_generic_eligibility_finds_an_unreviewed_repeat_purchase(self):
        response = self.client.get(reverse('product-reviews-eligibility', args=[self.product.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['eligible'])
        self.assertEqual(response.data['order_id'], self.unreviewed_order.id)

    def test_review_submission_requires_the_matching_delivered_order_item(self):
        response = self.client.post(
            reverse('product-reviews', args=[self.product.slug]),
            {
                'overall_rating': 5,
                'order': self.reviewed_order.id,
                'order_item': self.unreviewed_item.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(ProductReview.objects.count(), 1)
