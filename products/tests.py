import importlib
import uuid
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connections
from django.http import QueryDict
from django_redis.exceptions import ConnectionInterrupted
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch
from rest_framework.test import APIClient

from orders.models import Order, OrderItem
from products.models import Category, CategoryAttribute, FlashSale, Product, ProductReview, ProductVariant
from products.serializers import CategoryAttributeSerializer, CategorySerializer, FlashSaleSerializer, ProductSerializer
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
        self.trader = TraderApplication.objects.create(
            full_name='Seller Owner',
            email='seller-visibility@example.com',
            phone='0700000000',
            business_name='Visible Seller Shop',
            business_type='sole_proprietor',
            location='Kampala',
            product_categories='Seller Goods',
            status='approved',
        )
        self.seller_product = Product.objects.create(
            name='Seller Product',
            category=self.phone_category,
            price=15000,
            stock=3,
            is_active=True,
            review_status='approved',
            trader=self.trader,
        )
        self.trader_product = TraderProduct.objects.create(
            trader=self.trader,
            name='Linked Seller Product',
            price=18000,
            stock=2,
            category=self.phone_category,
        )
        self.linked_seller_product = Product.objects.create(
            name='Linked Seller Product',
            category=self.phone_category,
            price=18000,
            stock=2,
            is_active=True,
            review_status='approved',
            trader_product=self.trader_product,
        )

    def test_authenticated_user_gets_category_based_recommendations(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('product-recommendations'))

        self.assertEqual(response.status_code, 200)
        product_ids = [item['id'] for item in response.data]
        self.assertIn(self.related_product.id, product_ids)
        self.assertLess(product_ids.index(self.related_product.id), product_ids.index(self.other_product.id))

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


    def test_public_catalog_and_product_page_return_the_real_trader(self):
        listing = self.client.get(reverse('product-list'))
        detail = self.client.get(
            reverse('product-detail-by-slug', kwargs={'slug': self.seller_product.slug})
        )

        self.assertIn(self.seller_product.id, [item['id'] for item in listing.data['results']])
        self.assertIn(self.linked_seller_product.id, [item['id'] for item in listing.data['results']])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['seller_uuid'], str(self.trader.uuid))
        linked_detail = self.client.get(
            reverse('product-detail-by-slug', kwargs={'slug': self.linked_seller_product.slug})
        )
        self.assertEqual(linked_detail.status_code, 200)
        self.assertEqual(linked_detail.data['seller_uuid'], str(self.trader.uuid))

    def test_migration_links_unique_unowned_legacy_product_to_trader(self):
        image = 'products/rtc-module.jpg'
        trader_product = TraderProduct.objects.create(
            trader=self.trader,
            name='DS3231 AT24C32 High-Precision I2C Real-Time Clock (RTC) Module',
            price=18000,
            stock=2,
            image=image,
        )
        legacy_product = Product.objects.create(
            name='Legacy RTC module title',
            category=self.phone_category,
            price=18000,
            stock=2,
            image=image,
            is_active=True,
            review_status='approved',
        )
        migration = importlib.import_module(
            'products.migrations.0018_relink_unowned_trader_products'
        )

        migration.relink_unowned_trader_products(
            apps,
            SimpleNamespace(connection=connections['default']),
        )

        legacy_product.refresh_from_db()
        self.assertEqual(legacy_product.trader_id, self.trader.pk)
        self.assertEqual(legacy_product.trader_product_id, trader_product.pk)
        response = self.client.get(reverse('product-list'), {'seller': str(self.trader.uuid)})
        self.assertEqual(response.status_code, 200)
        seller_products = {
            item['id']: item for item in response.data['results']
        }
        self.assertIn(legacy_product.pk, seller_products)
        self.assertEqual(seller_products[legacy_product.pk]['seller_uuid'], str(self.trader.uuid))

    def test_migration_creates_unmatched_trader_product_for_admin_review(self):
        trader_product = TraderProduct.objects.create(
            trader=self.trader,
            name='2-Channel 5V Relay Module with Optocoupler Isolation',
            price=18000,
            stock=2,
            category=self.phone_category,
            is_active=True,
        )
        migration = importlib.import_module(
            'products.migrations.0019_create_missing_trader_public_products'
        )

        migration.create_missing_trader_public_products(
            apps,
            SimpleNamespace(connection=connections['default']),
        )

        public_product = Product.objects.get(trader_product=trader_product)
        self.assertEqual(public_product.trader_id, self.trader.pk)
        self.assertEqual(public_product.review_status, 'pending_review')
        self.assertFalse(public_product.is_active)
        listing = self.client.get(reverse('product-list'), {'seller': str(self.trader.uuid)})
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn(public_product.pk, [item['id'] for item in listing.data['results']])

    def test_closed_or_hidden_trader_products_are_not_listed_as_majo_products(self):
        for field in ('is_closed', 'is_visible'):
            with self.subTest(field=field):
                self.trader.is_closed = False
                self.trader.is_visible = True
                setattr(self.trader, field, field == 'is_closed')
                self.trader.save(update_fields=['is_closed', 'is_visible'])

                listing = self.client.get(reverse('product-list'))
                detail = self.client.get(
                    reverse('product-detail-by-slug', kwargs={'slug': self.seller_product.slug})
                )

                self.assertNotIn(self.seller_product.id, [item['id'] for item in listing.data['results']])
                self.assertNotIn(self.linked_seller_product.id, [item['id'] for item in listing.data['results']])
                self.assertEqual(detail.status_code, 404)

    def test_existing_unsigned_agreement_does_not_hide_approved_trader_products(self):
        self.trader.agreement_required = True
        self.trader.agreement_signed_at = None
        self.trader.save(update_fields=['agreement_required', 'agreement_signed_at'])

        listing = self.client.get(reverse('product-list'))
        detail = self.client.get(
            reverse('product-detail-by-slug', kwargs={'slug': self.seller_product.slug})
        )

        product_ids = [item['id'] for item in listing.data['results']]
        self.assertIn(self.seller_product.id, product_ids)
        self.assertIn(self.linked_seller_product.id, product_ids)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['seller_uuid'], str(self.trader.uuid))


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


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'marketplace-category-taxonomy-tests',
    },
})
class MarketplaceCategoryTaxonomyAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Category.objects.create(name='Test Department', slug='test-department')
        self.category = Category.objects.create(
            name='Test Category', slug='test-category', parent=self.department,
        )
        self.subcategory = Category.objects.create(name='Test Subcategory', slug='test-subcategory', parent=self.category)
        self.product = Product.objects.create(
            name='Test Board', category=self.subcategory, brand='Espressif',
            price=10000, stock=5, is_active=True, review_status='approved',
        )
        self.admin = User.objects.create_user(
            email='taxonomy-admin@example.com',
            password='strong-pass-123',
            name='Taxonomy Admin',
            is_staff=True,
        )

    def test_department_filter_includes_active_products_in_descendants(self):
        response = self.client.get(reverse('product-list'), {'category': 'test-department'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data['results']], [self.product.id])

    def test_category_list_returns_all_nodes_and_aggregated_product_counts(self):
        response = self.client.get(reverse('category-list'))

        self.assertEqual(response.status_code, 200)
        categories = {item['slug']: item for item in response.data}
        self.assertEqual(categories['test-department']['product_count'], 1)
        self.assertEqual(categories['test-category']['product_count'], 1)
        self.assertEqual(categories['test-subcategory']['product_count'], 1)

    def test_fashion_department_and_category_have_distinct_parent_relationships(self):
        department = Category.objects.get(slug='fashion-accessories')
        category = Category.objects.get(slug='fashion-accessories-fashion-accessories')

        self.assertIsNone(department.parent_id)
        self.assertEqual(department.name, 'Fashion & Accessories')
        self.assertEqual(category.parent_id, department.pk)

    def test_category_delete_deactivates_and_keeps_product_assignment(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.delete(reverse('category-detail', args=[self.subcategory.pk]))

        self.assertEqual(response.status_code, 204)
        self.product.refresh_from_db()
        self.assertEqual(self.product.category_id, self.subcategory.pk)
        self.subcategory.refresh_from_db()
        self.assertFalse(self.subcategory.is_active)

    def test_search_matches_category_hierarchy_and_brand(self):
        response = self.client.get(reverse('product-list'), {'search': 'Espressif'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data['results']], [self.product.id])


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

    def test_product_can_be_updated_when_uuid_is_a_string(self):
        product_uuid = str(self.existing_product.uuid)
        self.existing_product.uuid = product_uuid
        self.existing_product.name = 'Updated Product'

        self.existing_product.save()

        self.assertEqual(self.existing_product.slug, f'updated-product-{uuid.UUID(product_uuid).hex[:12]}')
        self.existing_product.refresh_from_db()
        self.assertEqual(self.existing_product.name, 'Updated Product')

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

    def test_trader_can_update_own_linked_product_through_product_detail_endpoint(self):
        trader_user = User.objects.create_user(email='owner@example.com', name='Owner', password='Password123!')
        trader = TraderApplication.objects.create(
            full_name='Owner', email='owner@example.com', phone='0700000000',
            business_name='Owner Store', business_type='sole_proprietor',
            location='Kampala', district='Central', product_categories='Phones',
            status='approved', user=trader_user,
        )
        trader_product = TraderProduct.objects.create(
            trader=trader, name='Inactive Product', price='100.00', stock=2,
            is_active=False,
        )
        product = Product.objects.create(
            name='Inactive Product', category=self.category, price='100.00',
            stock=2, is_active=False, trader=trader, trader_product=trader_product,
        )
        self.client.force_authenticate(user=trader_user)

        response = self.client.patch(
            reverse('product-detail', args=[product.id]),
            {'name': 'Updated Product', 'price': '150.00', 'is_active': True},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        trader_product.refresh_from_db()
        self.assertEqual(product.name, 'Updated Product')
        self.assertEqual(product.price, 150)
        self.assertTrue(product.is_active)
        self.assertEqual(trader_product.name, product.name)
        self.assertEqual(trader_product.price, product.price)
        self.assertTrue(trader_product.is_active)

    def test_trader_cannot_update_another_traders_product_through_product_detail_endpoint(self):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='Password123!')
        trader = TraderApplication.objects.create(
            full_name='Owner', email='owner@example.com', phone='0700000000',
            business_name='Owner Store', business_type='sole_proprietor',
            location='Kampala', district='Central', product_categories='Phones',
            status='approved', user=owner,
        )
        product = Product.objects.create(
            name='Other Product', category=self.category, price='100.00',
            stock=2, trader=trader,
        )
        other_owner = User.objects.create_user(email='other@example.com', name='Other', password='Password123!')
        TraderApplication.objects.create(
            full_name='Other', email='other@example.com', phone='0700000001',
            business_name='Other Store', business_type='sole_proprietor',
            location='Jinja', district='Eastern', product_categories='Phones',
            status='approved', user=other_owner,
        )
        self.client.force_authenticate(user=other_owner)

        response = self.client.patch(
            reverse('product-detail', args=[product.id]),
            {'name': 'Unauthorized Change'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        product.refresh_from_db()
        self.assertEqual(product.name, 'Other Product')

    def test_trader_can_delete_own_product_through_product_detail_endpoint(self):
        trader_user = User.objects.create_user(email='owner@example.com', name='Owner', password='Password123!')
        trader = TraderApplication.objects.create(
            full_name='Owner', email='owner@example.com', phone='0700000000',
            business_name='Owner Store', business_type='sole_proprietor',
            location='Kampala', district='Central', product_categories='Phones',
            status='approved', user=trader_user,
        )
        product = Product.objects.create(
            name='Owner Product', category=self.category, price='100.00',
            stock=2, trader=trader,
        )
        self.client.force_authenticate(user=trader_user)

        response = self.client.delete(reverse('product-detail', args=[product.id]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_trader_cannot_delete_another_traders_product_through_product_detail_endpoint(self):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='Password123!')
        trader = TraderApplication.objects.create(
            full_name='Owner', email='owner@example.com', phone='0700000000',
            business_name='Owner Store', business_type='sole_proprietor',
            location='Kampala', district='Central', product_categories='Phones',
            status='approved', user=owner,
        )
        product = Product.objects.create(
            name='Other Product', category=self.category, price='100.00',
            stock=2, trader=trader,
        )
        other_owner = User.objects.create_user(email='other@example.com', name='Other', password='Password123!')
        TraderApplication.objects.create(
            full_name='Other', email='other@example.com', phone='0700000001',
            business_name='Other Store', business_type='sole_proprietor',
            location='Jinja', district='Eastern', product_categories='Phones',
            status='approved', user=other_owner,
        )
        self.client.force_authenticate(user=other_owner)

        response = self.client.delete(reverse('product-detail', args=[product.id]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

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


class FlashSaleBasePricingSerializerTest(TestCase):
    def test_base_prices_are_stored_and_responses_apply_platform_charges(self):
        settings = PlatformSettings.get()
        settings.commission = 10
        settings.vat = 0
        settings.save()

        category = Category.objects.create(name='Accessories', slug='accessories')
        product = Product.objects.create(
            name='Headphones', category=category, price=100000, original_price=120000,
            stock=5, is_active=True,
        )
        sale = FlashSale.objects.create(
            product=product, flash_price=80000,
            ends_at='2099-01-01T12:00:00Z', stock_limit=5,
        )

        data = FlashSaleSerializer(sale).data
        self.assertEqual(data['product']['listed_price'], '100000.00')
        self.assertEqual(data['product']['price'], '110000.00')
        self.assertEqual(data['base_flash_price'], '80000.00')
        self.assertEqual(data['flash_price'], '88000.00')

        update = FlashSaleSerializer(sale, data={'flash_price': '90000.00'}, partial=True)
        self.assertTrue(update.is_valid(), update.errors)
        updated_sale = update.save()
        self.assertEqual(updated_sale.flash_price, 90000)
        self.assertEqual(update.data['base_flash_price'], '90000.00')
        self.assertEqual(update.data['flash_price'], '99000.00')


class ConfigurableProductCatalogTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name='Test Shoes', slug='configurable-test-shoes')
        CategoryAttribute.objects.create(
            category=self.category,
            name='Size',
            key='size',
            input_type='size',
            is_required=True,
            is_variant=True,
        )
        CategoryAttribute.objects.create(
            category=self.category,
            name='Color',
            key='color',
            input_type='color',
            choices=['Black', 'White'],
            is_required=True,
            is_variant=True,
        )
        CategoryAttribute.objects.create(
            category=self.category,
            name='Material',
            key='material',
            input_type='text',
            is_required=True,
        )

    def test_category_serializer_saves_hierarchy_and_dynamic_attributes(self):
        parent = Category.objects.create(name='Test Fashion', slug='configurable-test-fashion')
        serializer = CategorySerializer(data={
            'name': 'Clothing',
            'parent_id': parent.pk,
            'attributes': [{
                'name': 'Fit',
                'input_type': 'dropdown',
                'choices': ['Slim', 'Regular'],
                'is_required': True,
            }],
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        category = serializer.save()
        self.assertEqual(category.parent, parent)
        self.assertEqual(category.attributes.get().key, 'fit')
        self.assertEqual(category.attributes.get().choices, ['Slim', 'Regular'])

    def test_text_attributes_accept_suggestions_and_allow_custom_values(self):
        serializer = CategoryAttributeSerializer(data={
            'name': 'Product Type',
            'input_type': 'text',
            'choices': ['T-Shirt', 'Other'],
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['choices'], ['T-Shirt', 'Other'])

    def test_seeded_clothing_and_shoe_categories_have_variant_and_specification_attributes(self):
        clothing = Category.objects.get(slug='clothing')
        shoe_root = Category.objects.get(slug='shoes')
        clothing_keys = set(clothing.attributes.values_list('key', flat=True))
        shoe_keys = set(shoe_root.attributes.values_list('key', flat=True))

        self.assertTrue({'product-type', 'gender', 'material', 'material-composition', 'pattern', 'fit',
                         'care-instructions', 'size-system', 'size', 'color'}.issubset(clothing_keys))
        self.assertTrue({'product-type', 'gender', 'material', 'sole-material', 'style', 'intended-use',
                         'size-system', 'size', 'color'}.issubset(shoe_keys))
        self.assertTrue(shoe_root.children.exists())
        self.assertTrue(all(
            {'size', 'color'}.issubset(set(category.attributes.values_list('key', flat=True)))
            for category in shoe_root.children.all()
        ))

    def test_product_serializer_persists_specifications_and_variants(self):
        serializer = ProductSerializer(data={
            'name': 'Running Shoe',
            'category_id': self.category.pk,
            'price': '100.00',
            'stock': 3,
            'specifications': {'material': 'Mesh'},
            'variants': [{
                'sku': 'SHOE-BLACK-9',
                'options': {'size': '9', 'color': 'Black'},
                'price': '100.00',
                'stock': 3,
            }],
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        product = serializer.save()
        self.assertEqual(product.specifications, {'material': 'Mesh'})
        self.assertEqual(product.review_status, 'approved')
        self.assertEqual(product.variants.count(), 1)
        self.assertEqual(product.stock, 3)

    def test_each_required_variant_option_must_be_present(self):
        serializer = ProductSerializer(data={
            'name': 'Incomplete Running Shoe',
            'category_id': self.category.pk,
            'price': '100.00',
            'stock': 3,
            'specifications': {'material': 'Mesh'},
            'variants': [{
                'sku': 'SHOE-MISSING-COLOR',
                'options': {'size': '9'},
                'price': '100.00',
                'stock': 3,
            }],
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('Each variant must include Color.', str(serializer.errors['variants']))

    def test_adding_variants_to_legacy_product_enforces_category_options(self):
        product = Product.objects.create(
            name='Legacy Running Shoe',
            category=self.category,
            price='100.00',
            stock=3,
            specifications={'material': 'Mesh'},
        )
        serializer = ProductSerializer(product, data={
            'variants': [{
                'options': {'size': '9'},
                'price': '100.00',
                'stock': 3,
            }],
        }, partial=True)

        self.assertFalse(serializer.is_valid())
        self.assertIn('Each variant must include Color.', str(serializer.errors['variants']))

    def test_variant_attributes_are_filterable_and_searchable(self):
        product = Product.objects.create(
            name='Mesh Running Shoe',
            category=self.category,
            price='100.00',
            stock=2,
            specifications={'material': ['Mesh']},
        )
        ProductVariant.objects.create(
            product=product,
            options={'size': '42', 'color': 'Black'},
            price='100.00',
            stock=2,
        )

        filtered = self.client.get(reverse('product-list'), {
            'category': self.category.slug,
            'attr_size': '42',
        })
        searched = self.client.get(reverse('product-list'), {'search': '42'})

        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertIn(product.id, [item['id'] for item in filtered.data['results']])
        self.assertEqual(searched.status_code, 200, searched.data)
        self.assertIn(product.id, [item['id'] for item in searched.data['results']])

    def test_product_serializer_parses_variants_from_multipart_form_data(self):
        data = QueryDict('', mutable=True)
        data.update({
            'name': 'Multipart Running Shoe',
            'category_id': str(self.category.pk),
            'price': '100.00',
            'stock': '3',
            'specifications': '{"material":"Mesh"}',
            'variants': '[{"sku":"SHOE-BLACK-9","options":{"size":"9","color":"Black"},"price":"100.00","stock":3}]',
        })
        serializer = ProductSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        product = serializer.save()
        self.assertEqual(product.variants.count(), 1)
        self.assertEqual(product.specifications, {'material': 'Mesh'})

    def test_product_representation_exposes_unmodified_listed_prices_for_editing(self):
        product = Product.objects.create(
            name='Price-safe Product',
            category=self.category,
            price='22000.00',
            original_price='44000.00',
        )

        data = ProductSerializer(product).data

        self.assertEqual(data['listed_price'], '22000.00')
        self.assertEqual(data['original_listed_price'], '44000.00')

    def test_updating_variant_without_new_image_preserves_image_and_identity(self):
        product = Product.objects.create(
            name='Color LED',
            category=Category.objects.create(name='Lights', slug='lights'),
            price=100,
            stock=3,
            specifications={'material': 'Plastic'},
        )
        variant = ProductVariant.objects.create(
            product=product,
            sku='LED-RED',
            options={'color': 'Red'},
            price=100,
            stock=3,
            image='product_variants/red-led.jpg',
        )
        serializer = ProductSerializer(product, data={
            'variants': [{
                'sku': 'LED-RED',
                'options': {'color': 'Red'},
                'price': '110.00',
                'stock': 2,
            }],
        }, partial=True)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        variant.refresh_from_db()
        self.assertEqual(str(variant.image), 'product_variants/red-led')
        self.assertEqual(variant.price, 110)
        self.assertEqual(variant.stock, 2)
        self.assertEqual(product.variants.count(), 1)

    def test_required_category_values_are_validated(self):
        serializer = ProductSerializer(data={
            'name': 'Incomplete Shoe',
            'category_id': self.category.pk,
            'price': '100.00',
            'stock': 1,
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('specifications', serializer.errors)
        self.assertIn('variants', serializer.errors)

    def test_variant_with_order_history_cannot_be_removed(self):
        product = Product.objects.create(
            name='Ordered Shoe',
            category=self.category,
            price='100.00',
            stock=1,
        )
        variant = ProductVariant.objects.create(
            product=product,
            sku='ORDERED-SHOE-9',
            options={'size': '9', 'color': 'Black'},
            price='100.00',
            stock=1,
        )
        user = User.objects.create_user(
            email='ordered-shoe-customer@example.com',
            name='Shoe Customer',
            password='Password123!',
        )
        order = Order.objects.create(user=user, total='100.00')
        OrderItem.objects.create(
            order=order,
            product=product,
            variant=variant,
            variant_options=variant.options,
            variant_sku=variant.sku,
            quantity=1,
            price='100.00',
        )

        public_variant_data = ProductSerializer(product).data['variants'][0]
        self.assertNotIn('sold_quantity', public_variant_data)
        admin = User.objects.create_user(
            email='shoe-admin@example.com',
            name='Shoe Admin',
            password='Password123!',
            is_staff=True,
        )
        admin_variant_data = ProductSerializer(
            product,
            context={'request': SimpleNamespace(user=admin)},
        ).data['variants'][0]
        self.assertEqual(admin_variant_data['sold_quantity'], 1)

        serializer = ProductSerializer(product, data={'variants': []}, partial=True)

        self.assertFalse(serializer.is_valid())
        self.assertIn('order or inventory history', str(serializer.errors['variants']))
        self.assertTrue(ProductVariant.objects.filter(pk=variant.pk).exists())

    def test_review_action_requires_feedback_and_controls_public_visibility(self):
        admin = User.objects.create_user(
            email='product-admin@example.com',
            password='strong-pass-123',
            name='Product Admin',
            is_staff=True,
        )
        product = Product.objects.create(
            name='Review Shoe',
            category=Category.objects.create(name='Accessories', slug='accessories'),
            price=100,
            stock=2,
            is_active=False,
            review_status='pending_review',
        )
        self.client.force_authenticate(user=admin)
        review_url = reverse('product-review-status', args=[product.pk])

        missing_reason = self.client.post(review_url, {'review_status': 'changes_required'})
        self.assertEqual(missing_reason.status_code, 400)

        requested_changes = self.client.post(review_url, {
            'review_status': 'changes_required',
            'review_note': 'Add a clear product image.',
        })
        self.assertEqual(requested_changes.status_code, 200)
        self.assertEqual(requested_changes.data['review_note'], 'Add a clear product image.')
        self.assertEqual(
            APIClient().get(reverse('product-detail-by-slug', args=[product.slug])).status_code,
            404,
        )

        approved = self.client.post(review_url, {'review_status': 'approved'})
        self.assertEqual(approved.status_code, 200)
        self.assertTrue(approved.data['is_active'])
        self.assertEqual(approved.data['review_status'], 'approved')
