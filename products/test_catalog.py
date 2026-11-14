import importlib
import json
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from django.apps import apps
from django.db import connection
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase
from unittest.mock import patch

from products.catalog import merge_catalog_products
from products.models import CatalogProduct, CatalogVariant, Category, Product, ProductVariant
from traders.models import TraderApplication, TraderProduct


class SharedCatalogAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            email='catalog-seller@example.com',
            password='strong-pass-123',
            name='Catalog Seller',
        )
        self.category = Category.objects.create(name='Meters', slug='catalog-test-meters')
        self.trader = TraderApplication.objects.create(
            full_name='Catalog Seller',
            email=self.user.email,
            phone='0700000000',
            business_name='Catalog Test Shop',
            business_type='sole_proprietor',
            location='Kampala',
            product_categories='Meters',
            status='approved',
            user=self.user,
        )
        self.client.force_authenticate(self.user)
        self.catalog_product = CatalogProduct.objects.create(
            name='ANENG M118A Digital Multimeter',
            brand='ANENG',
            model='M118A',
            product_type='Digital multimeter',
            category=self.category,
            short_description='Compact digital multimeter',
            specifications={'display': 'LCD'},
            identifiers={'mpn': 'M118A-UG'},
            image_references=['catalog/aneng-m118a-front'],
            review_status='approved',
            is_active=True,
        )

    def test_search_matches_catalog_identifiers_and_never_returns_pending_products(self):
        CatalogProduct.objects.create(
            name='Unreviewed Product',
            model='UNREVIEWED-1',
            review_status='pending_review',
        )

        response = self.client.get(reverse('catalog-product-list'), {'q': 'M118A-UG'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data], [self.catalog_product.id])
        self.assertEqual(response.data[0]['image_references'], ['catalog/aneng-m118a-front'])

    def test_browse_returns_approved_catalog_products_and_hides_unapproved(self):
        CatalogProduct.objects.create(
            name='Pending Product',
            model='PENDING-1',
            review_status='pending_review',
            is_active=False,
        )
        CatalogProduct.objects.create(
            name='Disabled Product',
            model='DISABLED-1',
            review_status='disabled',
            is_active=False,
        )

        response = self.client.get(reverse('catalog-product-browse'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual([item['id'] for item in response.data['results']], [self.catalog_product.id])
        self.assertEqual(response.data['results'][0]['image_references'], ['catalog/aneng-m118a-front'])

    def test_new_catalog_requests_are_pending_and_exclude_offer_fields(self):
        response = self.client.post(reverse('catalog-product-list'), {
            'name': 'Bench Power Supply BX-1',
            'brand': 'BenchCo',
            'model': 'BX-1',
            'category_id': self.category.id,
            'specifications': {'voltage': '30V'},
            'offer_details': {
                'price': '120000',
                'original_price': '145000',
                'stock': 4,
                'trader_sku': 'BX-1-LOCAL',
                'delivery_fee': '5000',
                'condition': 'new',
                'availability': 'in_stock',
                'warranty': '12 months',
                'delivery_options': ['Pickup', 'Courier'],
                'package_details': 'Power supply, probes, manual',
                'variants': [{
                    'sku': 'BX-1-30V',
                    'options': {'voltage': '30V'},
                    'price': '120000',
                    'compare_at_price': '145000',
                    'stock': 4,
                    'is_active': True,
                }],
            },
        }, format='json')

        self.assertEqual(response.status_code, 201)
        product = CatalogProduct.objects.get(pk=response.data['id'])
        self.assertEqual(product.review_status, 'pending_review')
        self.assertFalse(product.is_active)
        self.assertEqual(product.created_by, self.user)
        self.assertFalse(hasattr(product, 'price'))
        self.assertFalse(hasattr(product, 'stock'))
        self.assertFalse(hasattr(product, 'trader_sku'))
        self.assertEqual(product.request_offer_details['price'], '120000.00')
        self.assertEqual(product.request_offer_details['variants'][0]['options'], {'voltage': '30V'})

    def test_requester_can_review_own_request_and_admin_can_approve_it(self):
        response = self.client.post(reverse('catalog-product-list'), {
            'name': 'Laboratory Supply P-220',
            'brand': 'BenchCo',
            'model': 'P-220',
            'category_id': self.category.id,
            'short_description': 'Adjustable power supply',
            'long_description': 'A laboratory power supply with adjustable voltage.',
            'offer_details': {
                'price': '180000',
                'original_price': '205000',
                'stock': 3,
                'condition': 'new',
                'availability': 'in_stock',
                'variants': [{
                    'sku': 'P-220-220V',
                    'options': {'voltage': '220V'},
                    'price': '180000',
                    'compare_at_price': '205000',
                    'stock': 3,
                }],
            },
        }, format='json')
        self.assertEqual(response.status_code, 201)
        request_id = response.data['id']

        own_requests = self.client.get(reverse('catalog-product-requests'))
        self.assertEqual(own_requests.status_code, 200)
        self.assertEqual([item['id'] for item in own_requests.data], [request_id])
        self.assertEqual(
            self.client.get(reverse('admin-catalog-product-requests')).status_code,
            403,
        )

        admin = get_user_model().objects.create_superuser(
            email='catalog-admin@example.com',
            password='strong-pass-123',
            name='Catalog Admin',
        )
        self.client.force_authenticate(admin)
        admin_requests = self.client.get(reverse('admin-catalog-product-requests'))
        self.assertEqual(admin_requests.status_code, 200)
        self.assertEqual(admin_requests.data[0]['requester_email'], self.user.email)

        approved = self.client.patch(
            reverse('admin-catalog-product-request', args=[request_id]),
            {'review_status': 'approved'},
            format='json',
        )
        self.assertEqual(approved.status_code, 200)
        product = CatalogProduct.objects.get(pk=request_id)
        self.assertTrue(product.is_active)
        self.assertEqual(product.review_status, 'approved')
        self.assertTrue(product.variants.filter(options={'voltage': '220V'}).exists())
        self.assertEqual(approved.data['request_offer_details']['price'], '180000.00')

    def test_admin_can_edit_request_before_approval_and_rejection_requires_reason(self):
        response = self.client.post(reverse('catalog-product-list'), {
            'name': 'Bench Supply E-100',
            'brand': 'BenchCo',
            'model': 'E-100',
            'offer_details': {'price': '40000'},
        }, format='json')
        self.assertEqual(response.status_code, 201)
        request_id = response.data['id']
        admin = get_user_model().objects.create_superuser(
            email='catalog-editor@example.com',
            password='strong-pass-123',
            name='Catalog Editor',
        )
        self.client.force_authenticate(admin)

        invalid_rejection = self.client.patch(
            reverse('admin-catalog-product-request', args=[request_id]),
            {'review_status': 'rejected'},
            format='json',
        )
        self.assertEqual(invalid_rejection.status_code, 400)
        self.assertIn('review_note', invalid_rejection.data)

        edited = self.client.patch(
            reverse('admin-catalog-product-request', args=[request_id]),
            {
                'name': 'Bench Supply E-100 Updated',
                'offer_details': {'price': '45000', 'stock': 8},
            },
            format='json',
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.data['name'], 'Bench Supply E-100 Updated')
        self.assertEqual(edited.data['request_offer_details']['price'], '45000.00')

    def test_request_accepts_multipart_images_and_variant_image_indexes(self):
        image_buffer = BytesIO()
        Image.new('RGB', (1, 1), color='white').save(image_buffer, format='PNG')
        image_data = image_buffer.getvalue()
        payload = {
            'name': 'Bench Supply Image Test',
            'brand': 'BenchCo',
            'model': 'IMG-1',
            'offer_details': json.dumps({
                'price': '45000',
                'variants': [{
                    'sku': 'IMG-1-RED',
                    'options': {'color': 'Red'},
                    'price': '45000',
                    'stock': 2,
                }],
                'variant_image_indexes': [0],
            }),
            'images[0]': SimpleUploadedFile('product.png', image_data, content_type='image/png'),
        }
        with patch('products.catalog.CatalogProductImage.objects.create') as create_image:
            response = self.client.post(reverse('catalog-product-list'), payload, format='multipart')

        self.assertEqual(response.status_code, 201)
        create_image.assert_called_once()
        self.assertEqual(create_image.call_args.kwargs['variant_options'], {'color': 'Red'})

    def test_duplicate_request_is_blocked_by_model_or_identifier_not_trader_sku(self):
        response = self.client.post(reverse('catalog-product-list'), {
            'name': 'ANENG M118A Mini Multimeter Tester',
            'brand': 'ANENG',
            'model': 'M118A',
            'identifiers': {'barcode': '0123456789012'},
            'offer_details': {'price': '45000'},
        }, format='json')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['matches'][0]['id'], self.catalog_product.id)
        self.assertEqual(CatalogProduct.objects.count(), 1)

    def test_existing_product_backfill_preserves_ids_and_cloudinary_references(self):
        offer = TraderProduct.objects.create(
            trader=self.trader,
            name='Legacy multimeter offer',
            price='45000',
            stock=3,
            category=self.category,
        )
        legacy = Product.objects.create(
            name='ANENG M118A Digital Multimeter',
            brand='ANENG',
            category=self.category,
            price='45000',
            stock=3,
            trader=self.trader,
            trader_product=offer,
            specifications={'model_number': 'M118A'},
            review_status='approved',
            is_active=True,
        )
        legacy_id = legacy.pk
        Product.objects.filter(pk=legacy.pk).update(image='catalog/legacy-m118a-front')
        ProductVariant.objects.create(
            product=legacy,
            sku='LEGACY-M118A-RED',
            options={'color': 'Red'},
            price='45000',
            stock=3,
        )
        backfill = importlib.import_module(
            'traders.migrations.0017_backfill_catalog_from_products'
        )

        backfill.backfill_catalog_from_products(apps, SimpleNamespace(connection=connection))

        legacy.refresh_from_db()
        offer.refresh_from_db()
        self.assertEqual(legacy.pk, legacy_id)
        self.assertEqual(offer.catalog_product_id, legacy.catalog_product_id)
        self.assertEqual(legacy.catalog_product.name, legacy.name)
        self.assertEqual(legacy.catalog_product.model, 'M118A')
        self.assertEqual(legacy.catalog_product.image_references, ['catalog/legacy-m118a-front'])
        self.assertEqual(legacy.catalog_product.variant_options, [{'color': 'Red'}])
        self.assertEqual(offer.catalog_image_references, ['catalog/legacy-m118a-front'])

    def test_follow_up_migration_links_products_created_after_original_backfill(self):
        offer = TraderProduct.objects.create(
            trader=self.trader,
            name='Post-backfill multimeter offer',
            price='45000',
            stock=3,
            category=self.category,
        )
        product = Product.objects.create(
            name='Post-backfill multimeter',
            brand='BenchCo',
            category=self.category,
            price='45000',
            stock=3,
            trader=self.trader,
            trader_product=offer,
            specifications={'model_number': 'POST-BACKFILL-1'},
            review_status='approved',
            is_active=True,
        )
        Product.objects.filter(pk=product.pk).update(image='catalog/post-backfill-front')
        ProductVariant.objects.create(
            product=product,
            sku='POST-BACKFILL-RED',
            options={'color': 'Red'},
            price='45000',
            stock=3,
        )
        migration = importlib.import_module(
            'products.migrations.0027_link_products_to_shared_catalog'
        )

        migration.link_products_to_shared_catalog(apps, SimpleNamespace(connection=connection))

        product.refresh_from_db()
        offer.refresh_from_db()
        self.assertIsNotNone(product.catalog_product_id)
        self.assertEqual(offer.catalog_product_id, product.catalog_product_id)
        self.assertEqual(product.catalog_product.image_references, ['catalog/post-backfill-front'])
        self.assertEqual(product.catalog_product.variant_options, [{'color': 'Red'}])
        self.assertEqual(offer.catalog_image_references, ['catalog/post-backfill-front'])

    def test_admin_product_creation_adds_product_to_shared_catalog(self):
        admin = get_user_model().objects.create_superuser(
            email='catalog-product-admin@example.com',
            password='strong-pass-123',
            name='Catalog Product Admin',
        )
        self.client.force_authenticate(admin)

        response = self.client.post(reverse('product-list'), {
            'name': 'Admin Shared Catalog Tester',
            'brand': 'BenchCo',
            'category_id': self.category.id,
            'price': '45000',
            'stock': 3,
            'specifications': {'model_number': 'ADMIN-TEST-1'},
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        product = Product.objects.get(pk=response.data['id'])
        self.assertIsNotNone(product.catalog_product_id)
        self.assertEqual(product.catalog_product.model, 'ADMIN-TEST-1')
        self.assertEqual(product.catalog_product.review_status, 'approved')

        new_trader_client = APIClient()
        new_trader_client.force_authenticate(self.user)
        catalog_response = new_trader_client.get(
            reverse('catalog-product-list'),
            {'q': 'ADMIN-TEST-1'},
        )
        self.assertEqual(catalog_response.status_code, 200)
        self.assertEqual(
            [item['id'] for item in catalog_response.data],
            [product.catalog_product_id],
        )

    def test_approved_trader_product_is_added_to_shared_catalog(self):
        offer = TraderProduct.objects.create(
            trader=self.trader,
            name='Trader Shared Catalog Tester',
            price='45000',
            stock=3,
            category=self.category,
        )
        product = Product.objects.create(
            name='Trader Shared Catalog Tester',
            brand='BenchCo',
            category=self.category,
            price='45000',
            stock=3,
            trader=self.trader,
            trader_product=offer,
            specifications={'model_number': 'TRADER-TEST-1'},
            review_status='pending_review',
            is_active=False,
        )
        admin = get_user_model().objects.create_superuser(
            email='catalog-review-admin@example.com',
            password='strong-pass-123',
            name='Catalog Review Admin',
        )
        self.client.force_authenticate(admin)

        response = self.client.post(
            reverse('product-review-status', args=[product.pk]),
            {'review_status': 'approved'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        product.refresh_from_db()
        offer.refresh_from_db()
        self.assertIsNotNone(product.catalog_product_id)
        self.assertEqual(offer.catalog_product_id, product.catalog_product_id)
        self.assertEqual(product.catalog_product.review_status, 'approved')
        self.assertTrue(product.catalog_product.is_active)

        catalog_response = APIClient().get(
            reverse('catalog-product-list'),
            {'q': 'TRADER-TEST-1'},
        )
        self.assertEqual(catalog_response.status_code, 200)
        self.assertEqual(
            [item['id'] for item in catalog_response.data],
            [product.catalog_product_id],
        )

    def test_catalog_merge_reassigns_offers_without_deleting_public_product_ids(self):
        survivor = self.catalog_product
        duplicate = CatalogProduct.objects.create(
            name='ANENG M118A Mini Multimeter Tester',
            brand='ANENG',
            model='M118A-mini',
            category=self.category,
            image_references=['catalog/aneng-m118a-side'],
            review_status='approved',
            is_active=True,
        )
        offer = TraderProduct.objects.create(
            trader=self.trader,
            catalog_product=duplicate,
            name=duplicate.name,
            price='42000',
            stock=2,
            category=self.category,
        )
        public_product = Product.objects.create(
            name=duplicate.name,
            category=self.category,
            price='42000',
            stock=2,
            trader=self.trader,
            trader_product=offer,
            catalog_product=duplicate,
            review_status='approved',
            is_active=True,
        )
        survivor_variant = CatalogVariant.objects.create(
            catalog_product=survivor,
            options={'color': 'Red'},
            image_references=['catalog/red-shared'],
        )
        source_variant = CatalogVariant.objects.create(
            catalog_product=duplicate,
            options={'color': 'Red'},
            image_references=['catalog/red-source'],
        )
        offer_variant = ProductVariant.objects.create(
            product=public_product,
            catalog_variant=source_variant,
            options={'color': 'Red'},
            price='42000',
        )

        merged, count = merge_catalog_products([duplicate.pk], survivor.pk)

        public_product.refresh_from_db()
        offer.refresh_from_db()
        duplicate.refresh_from_db()
        survivor.refresh_from_db()
        offer_variant.refresh_from_db()
        survivor_variant.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(merged.pk, survivor.pk)
        self.assertEqual(public_product.pk, public_product.id)
        self.assertEqual(public_product.catalog_product_id, survivor.pk)
        self.assertEqual(offer.catalog_product_id, survivor.pk)
        self.assertIn('catalog/aneng-m118a-side', survivor.image_references)
        self.assertEqual(offer_variant.catalog_variant_id, survivor_variant.pk)
        self.assertEqual(
            survivor_variant.image_references,
            ['catalog/red-shared', 'catalog/red-source'],
        )
        self.assertEqual(duplicate.review_status, 'disabled')
        self.assertFalse(duplicate.is_active)

    def test_offer_variants_link_to_shared_catalog_variants_and_reuse_images(self):
        self.catalog_product.variant_options = [{'color': 'Black'}]
        self.catalog_product.save(update_fields=('variant_options',))
        canonical = CatalogVariant.objects.create(
            catalog_product=self.catalog_product,
            options={'color': 'Black'},
            image_references=['catalog/black-variant'],
        )
        response = self.client.post(
            reverse('trader-products', kwargs={'trader_uuid': self.trader.uuid}),
            {
                'catalog_product_id': self.catalog_product.id,
                'category_id': self.category.id,
                'name': self.catalog_product.name,
                'price': '45000',
                'stock': 2,
                'variants': [{
                    'sku': 'BLACK-M118A',
                    'options': {'color': 'Black'},
                    'price': '45000',
                    'stock': 2,
                }],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        offer = TraderProduct.objects.get(uuid=response.data['uuid'])
        public_product = Product.objects.get(trader_product=offer)
        variant = public_product.variants.get()
        self.assertEqual(variant.catalog_variant, canonical)
        self.assertFalse(variant.image)
        self.assertEqual(variant.catalog_variant.image_references, ['catalog/black-variant'])
        catalog_response = self.client.get(reverse('catalog-product-list'), {'q': 'M118A'})
        self.assertEqual(catalog_response.status_code, 200)
        self.assertEqual(catalog_response.data[0]['variants'], [{
            'options': {'color': 'Black'},
            'image_references': ['catalog/black-variant'],
        }])

    def test_offer_rejects_variants_not_defined_by_the_shared_catalog(self):
        response = self.client.post(
            reverse('trader-products', kwargs={'trader_uuid': self.trader.uuid}),
            {
                'catalog_product_id': self.catalog_product.id,
                'category_id': self.category.id,
                'name': self.catalog_product.name,
                'price': '45000',
                'stock': 2,
                'variants': [{
                    'sku': 'UNLISTED-M118A',
                    'options': {'color': 'Green'},
                    'price': '45000',
                    'stock': 2,
                }],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('variants', response.data)
        self.assertFalse(TraderProduct.objects.exists())

    def test_catalog_request_rejects_trader_offer_fields(self):
        response = self.client.post(reverse('catalog-product-list'), {
            'name': 'Different product',
            'trader_sku': 'SELLER-UNIQUE-001',
            'price': '45000',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('trader_sku', response.data)
        self.assertIn('price', response.data)
        self.assertEqual(CatalogProduct.objects.count(), 1)

    def test_offer_attaches_shared_catalog_and_reuses_image_reference(self):
        response = self.client.post(
            reverse('trader-products', kwargs={'trader_uuid': self.trader.uuid}),
            {
                'catalog_product_id': self.catalog_product.id,
                'catalog_image_references': ['catalog/aneng-m118a-front'],
                'name': self.catalog_product.name,
                'brand': self.catalog_product.brand,
                'category_id': self.category.id,
                'short_description': self.catalog_product.short_description,
                'specifications': self.catalog_product.specifications,
                'trader_sku': 'SELLER-M118A-1',
                'condition': 'new',
                'price': '45000',
                'stock': 3,
                'delivery_fee': '0',
                'availability': 'preorder',
                'warranty': '12-month warranty',
                'delivery_options': ['Pickup', 'Kampala delivery'],
                'package_details': 'Includes carrying case',
                'submit_for_review': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        offer = TraderProduct.objects.get(uuid=response.data['uuid'])
        public_product = Product.objects.get(trader_product=offer)
        self.assertEqual(offer.catalog_product, self.catalog_product)
        self.assertEqual(offer.trader_sku, 'SELLER-M118A-1')
        self.assertEqual(offer.catalog_image_references, ['catalog/aneng-m118a-front'])
        self.assertEqual(offer.availability, 'preorder')
        self.assertEqual(offer.warranty, '12-month warranty')
        self.assertEqual(offer.delivery_options, ['Pickup', 'Kampala delivery'])
        self.assertEqual(offer.package_details, 'Includes carrying case')
        self.assertEqual(public_product.catalog_product, self.catalog_product)
        self.assertEqual(str(public_product.image), 'catalog/aneng-m118a-front')
        public_detail = self.client.get(reverse('product-detail', args=[public_product.pk]))
        self.assertEqual(public_detail.status_code, 200)
        self.assertEqual(public_detail.data['catalog_product_id'], self.catalog_product.pk)
        self.assertTrue(public_detail.data['images'])

        mutation = self.client.patch(
            reverse('product-detail', args=[public_product.pk]),
            {'name': 'Altered catalog name'},
            format='json',
        )
        self.assertEqual(mutation.status_code, 400)
        self.assertIn('name', mutation.data)

    def test_public_product_listing_shows_one_best_offer_per_catalog_product(self):
        best_offer = Product.objects.create(
            name=self.catalog_product.name,
            brand=self.catalog_product.brand,
            category=self.category,
            price='42000',
            stock=1,
            trader=self.trader,
            catalog_product=self.catalog_product,
            review_status='approved',
            is_active=True,
        )
        other_offer = Product.objects.create(
            name=self.catalog_product.name,
            brand=self.catalog_product.brand,
            category=self.category,
            price='45000',
            stock=4,
            trader=self.trader,
            catalog_product=self.catalog_product,
            review_status='approved',
            is_active=True,
        )

        response = self.client.get(reverse('product-list'))

        ids = [item['id'] for item in response.data['results']]
        self.assertIn(best_offer.pk, ids)
        self.assertNotIn(other_offer.pk, ids)

    def test_new_trader_offer_requires_an_approved_catalog_product(self):
        response = self.client.post(
            reverse('trader-products', kwargs={'trader_uuid': self.trader.uuid}),
            {'name': 'Unlinked product', 'price': '1000', 'stock': 1},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('catalog_product_id', response.data)
        self.assertFalse(TraderProduct.objects.exists())

    def test_public_catalog_offers_endpoint_returns_only_approved_active_offers(self):
        listed = Product.objects.create(
            name=self.catalog_product.name,
            brand=self.catalog_product.brand,
            category=self.category,
            price='45000',
            stock=3,
            trader=self.trader,
            catalog_product=self.catalog_product,
            review_status='approved',
            is_active=True,
        )
        Product.objects.create(
            name='Hidden seller copy',
            category=self.category,
            price='43000',
            stock=2,
            trader=self.trader,
            catalog_product=self.catalog_product,
            review_status='pending_review',
            is_active=False,
        )

        response = self.client.get(reverse(
            'catalog-product-offers', kwargs={'pk': self.catalog_product.pk},
        ))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([offer['id'] for offer in response.data], [listed.pk])

    def test_offer_cannot_override_shared_catalog_details(self):
        response = self.client.post(
            reverse('trader-products', kwargs={'trader_uuid': self.trader.uuid}),
            {
                'catalog_product_id': self.catalog_product.id,
                'name': 'Different official product name',
                'price': '45000',
                'stock': 3,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('name', response.data)
        self.assertFalse(TraderProduct.objects.exists())

    def test_offer_cannot_select_unapproved_shared_images(self):
        response = self.client.post(
            reverse('trader-products', kwargs={'trader_uuid': self.trader.uuid}),
            {
                'catalog_product_id': self.catalog_product.id,
                'catalog_image_references': ['not-approved/image'],
                'name': self.catalog_product.name,
                'brand': self.catalog_product.brand,
                'category_id': self.category.id,
                'short_description': self.catalog_product.short_description,
                'specifications': self.catalog_product.specifications,
                'price': '45000',
                'stock': 3,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('catalog_image_references', response.data)
        self.assertFalse(TraderProduct.objects.exists())
