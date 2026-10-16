from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from orders.models import Order, OrderItem
from products.models import Category, Product, ProductReview

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
