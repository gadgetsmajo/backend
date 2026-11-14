from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from products.models import CatalogProduct, Category, Product
from traders.models import TraderApplication, TraderProduct
from users.models import User

from .models import (
    AdvertisingCampaign,
    AdvertisingCampaignOffer,
    AdvertisingClick,
    AdvertisingPayment,
    AdvertisingWallet,
    AdvertisingWalletTransaction,
)


class AdvertisingAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='seller@example.test',
            name='Seller',
            password='Password123!',
        )
        self.buyer = User.objects.create_user(
            email='buyer@example.test',
            name='Buyer',
            password='Password123!',
        )
        self.admin = User.objects.create_user(
            email='admin@example.test',
            name='Admin',
            password='Password123!',
            is_staff=True,
        )
        self.trader = TraderApplication.objects.create(
            full_name='Seller',
            email=self.owner.email,
            phone='0700000000',
            business_name='Seller Store',
            business_type='sole_proprietor',
            location='Kampala',
            product_categories='Electronics',
            status='approved',
            user=self.owner,
        )
        self.category = Category.objects.create(name='Advertising Electronics', slug='advertising-electronics')
        self.catalog = CatalogProduct.objects.create(
            name='Test ESP32 board',
            brand='Majo',
            model='ESP32',
            category=self.category,
            image_references=['https://images.example.test/esp32.jpg'],
            review_status='approved',
            is_active=True,
        )
        self.offer = TraderProduct.objects.create(
            trader=self.trader,
            catalog_product=self.catalog,
            name='Test ESP32 board',
            price=Decimal('50000.00'),
            stock=5,
            category=self.category,
            image_url='https://images.example.test/esp32.jpg',
            is_active=True,
        )
        self.public_product = Product.objects.create(
            name='Test ESP32 board',
            category=self.category,
            price=Decimal('50000.00'),
            stock=5,
            trader=self.trader,
            trader_product=self.offer,
            catalog_product=self.catalog,
            is_active=True,
            review_status='approved',
        )
        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.buyer_client = APIClient()
        self.buyer_client.force_authenticate(self.buyer)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.campaign_url = f'/api/traders/{self.trader.uuid}/advertising/campaigns/'
        self.dashboard_url = f'/api/traders/{self.trader.uuid}/advertising/'
        self.recharge_url = f'/api/traders/{self.trader.uuid}/advertising/wallet/recharge/'

    def campaign_payload(self, offer_ids=None):
        from django.utils import timezone

        today = timezone.localdate()
        return {
            'name': 'ESP32 launch',
            'offer_ids': offer_ids or [self.offer.pk],
            'max_cpc': '300.00',
            'daily_budget': '5000.00',
            'total_budget': '30000.00',
            'starts_at': today.isoformat(),
            'ends_at': today.replace(year=today.year + 1).isoformat(),
        }

    def test_owner_offer_options_are_eligible_exact_trader_offers(self):
        unlisted_offer = TraderProduct.objects.create(
            trader=self.trader,
            catalog_product=self.catalog,
            name='Unlisted ESP32 offer',
            price=Decimal('50000.00'),
            stock=5,
            category=self.category,
            image_url='https://images.example.test/esp32.jpg',
            is_active=True,
        )
        response = self.owner_client.get(
            f'/api/traders/{self.trader.uuid}/advertising/offers/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.offer.pk)
        self.assertNotEqual(response.data[0]['id'], unlisted_offer.pk)
        self.assertEqual(response.data[0]['public_product_id'], self.public_product.pk)
        self.assertEqual(response.data[0]['slug'], self.public_product.slug)

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True)
    def _recharge(self, amount='1000.00', key='deposit-one'):
        return self.owner_client.post(
            self.recharge_url,
            {
                'amount': amount,
                'card_number': '5200 0000 0000 0114',
                'expiry': '07/28',
                'cvv': '123',
                'cardholder_name': 'Seller',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY=key,
        )

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True)
    def test_dummy_recharge_is_idempotent_and_never_persists_card_data(self):
        response = self._recharge()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['wallet']['balance'], '1000.00')
        self.assertEqual(response.data['payment']['status'], 'succeeded')

        repeated = self._recharge()
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(repeated.data['payment']['reference'], response.data['payment']['reference'])
        self.assertEqual(AdvertisingWallet.objects.get(trader=self.trader).balance, Decimal('1000.00'))
        self.assertEqual(AdvertisingPayment.objects.count(), 1)
        payment_fields = {field.name for field in AdvertisingPayment._meta.fields}
        self.assertFalse({'card_number', 'cvv', 'expiry'}.intersection(payment_fields))
        self.assertEqual(set(response.data), {'payment', 'wallet'})
        self.assertFalse({'card_number', 'cvv', 'expiry'}.intersection(response.data['payment']))

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True)
    def test_invalid_card_does_not_credit_wallet(self):
        response = self.owner_client.post(
            self.recharge_url,
            {
                'amount': '500.00',
                'card_number': '4111 1111 1111 1111',
                'expiry': '07/28',
                'cvv': '123',
                'cardholder_name': 'Seller',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='invalid-card',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AdvertisingWallet.objects.filter(trader=self.trader).exists())
        self.assertEqual(AdvertisingWalletTransaction.objects.count(), 0)

    @override_settings(DEBUG=False, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True)
    def test_dummy_payment_is_rejected_when_debug_is_false(self):
        response = self.owner_client.post(
            self.recharge_url,
            {
                'amount': '1000.00',
                'card_number': '5200 0000 0000 0114',
                'expiry': '07/28',
                'cvv': '123',
                'cardholder_name': 'Seller',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='production-attempt',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AdvertisingWallet.objects.filter(trader=self.trader).exists())

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True, ADVERTISING_REQUIRE_APPROVAL=True)
    def test_campaign_is_bound_to_exact_trader_offer_and_admin_approval(self):
        sibling = TraderProduct.objects.create(
            trader=self.trader,
            catalog_product=self.catalog,
            name='Sibling seller offer',
            price=Decimal('49000.00'),
            stock=8,
            category=self.category,
            image_url='https://images.example.test/esp32.jpg',
            is_active=True,
        )
        response = self.owner_client.post(self.campaign_url, self.campaign_payload(), format='json')
        self.assertEqual(response.status_code, 201)
        campaign = AdvertisingCampaign.objects.get(pk=response.data['campaign']['id'])
        row = campaign.offers.get()
        self.assertEqual(row.trader_offer_id, self.offer.pk)
        self.assertEqual(row.catalog_product_id, self.catalog.pk)
        self.assertNotEqual(row.trader_offer_id, sibling.pk)
        self.assertEqual(campaign.status, AdvertisingCampaign.Status.PENDING_REVIEW)

        approval = self.admin_client.patch(
            f'/api/advertising/admin/campaigns/{campaign.pk}/',
            {'action': 'approve'},
            format='json',
        )
        self.assertEqual(approval.status_code, 200)
        self.assertEqual(approval.data['campaign']['status'], AdvertisingCampaign.Status.PAUSED)
        # A campaign cannot spend until there are actual advertising funds.
        self.assertEqual(approval.data['campaign']['pause_reason'], 'insufficient_balance')

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True, ADVERTISING_REQUIRE_APPROVAL=True)
    def test_click_charges_once_and_repeat_is_suspicious_without_charge(self):
        self._recharge()
        created = self.owner_client.post(self.campaign_url, self.campaign_payload(), format='json')
        campaign_id = created.data['campaign']['id']
        self.admin_client.patch(
            f'/api/advertising/admin/campaigns/{campaign_id}/',
            {'action': 'approve'},
            format='json',
        )
        campaign_offer = AdvertisingCampaignOffer.objects.get(campaign_id=campaign_id)
        placement = self.buyer_client.get('/api/advertising/placements/?q=ESP32')
        self.assertEqual(placement.status_code, 200)
        self.assertEqual(placement.data['results'][0]['campaign_offer_id'], campaign_offer.pk)
        self.assertEqual(placement.data['results'][0]['public_product_id'], self.public_product.pk)
        exact_placement = self.buyer_client.get(
            f'/api/advertising/placements/?exact_product={self.public_product.pk}&limit=1'
        )
        self.assertEqual(exact_placement.status_code, 200)
        self.assertEqual(len(exact_placement.data['results']), 1)
        self.assertEqual(exact_placement.data['results'][0]['public_product_id'], self.public_product.pk)
        excluded = self.buyer_client.get(
            f'/api/advertising/placements/?exclude={self.public_product.pk}'
        )
        self.assertEqual(excluded.data['results'], [])
        impression = self.buyer_client.post(
            '/api/advertising/impressions/',
            {'campaign_offer_ids': [campaign_offer.pk]},
            format='json',
            HTTP_X_ADVERTISING_SESSION='buyer-session-1',
        )
        self.assertEqual(impression.data, {'accepted': 1, 'recorded': 1})
        duplicate_impression = self.buyer_client.post(
            '/api/advertising/impressions/',
            {'campaign_offer_ids': [campaign_offer.pk]},
            format='json',
            HTTP_X_ADVERTISING_SESSION='buyer-session-1',
        )
        self.assertEqual(duplicate_impression.data, {'accepted': 1, 'recorded': 0})

        first = self.buyer_client.post(
            '/api/advertising/clicks/',
            {'campaign_offer_id': campaign_offer.pk, 'idempotency_key': 'click-one'},
            format='json',
            HTTP_X_ADVERTISING_SESSION='buyer-session-1',
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['status'], 'valid')
        self.assertEqual(first.data['charged_amount'], '300.00')
        self.assertEqual(AdvertisingWallet.objects.get(trader=self.trader).balance, Decimal('700.00'))
        dashboard = self.owner_client.get(self.dashboard_url)
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.data['stats']['clicks'], 1)
        self.assertEqual(dashboard.data['stats']['total_spent'], '300.00')
        self.assertEqual(dashboard.data['campaigns'][0]['clicks'], 1)
        self.assertEqual(dashboard.data['campaigns'][0]['spent'], '300')

        repeated = self.buyer_client.post(
            '/api/advertising/clicks/',
            {'campaign_offer_id': campaign_offer.pk, 'idempotency_key': 'click-one'},
            format='json',
            HTTP_X_ADVERTISING_SESSION='buyer-session-1',
        )
        self.assertTrue(repeated.data['duplicate'])
        suspicious = self.buyer_client.post(
            '/api/advertising/clicks/',
            {'campaign_offer_id': campaign_offer.pk, 'idempotency_key': 'click-two'},
            format='json',
            HTTP_X_ADVERTISING_SESSION='buyer-session-1',
        )
        self.assertEqual(suspicious.data['status'], 'suspicious')
        self.assertEqual(suspicious.data['charged_amount'], '0.00')
        self.assertEqual(AdvertisingWallet.objects.get(trader=self.trader).balance, Decimal('700.00'))
        self.assertEqual(AdvertisingClick.objects.filter(status='valid').count(), 1)

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True, ADVERTISING_REQUIRE_APPROVAL=True)
    def test_public_placements_prioritize_offers_without_a_viewer_impression(self):
        second_catalog = CatalogProduct.objects.create(
            name='Test USB power adapter',
            brand='Majo',
            model='USB-12V',
            category=self.category,
            image_references=['https://images.example.test/adapter.jpg'],
            review_status='approved',
            is_active=True,
        )
        second_offer = TraderProduct.objects.create(
            trader=self.trader,
            catalog_product=second_catalog,
            name='Test USB power adapter',
            price=Decimal('25000.00'),
            stock=5,
            category=self.category,
            image_url='https://images.example.test/adapter.jpg',
            is_active=True,
        )
        Product.objects.create(
            name=second_offer.name,
            category=self.category,
            price=second_offer.price,
            stock=second_offer.stock,
            trader=self.trader,
            trader_product=second_offer,
            catalog_product=second_catalog,
            is_active=True,
            review_status='approved',
        )
        self._recharge()
        created = self.owner_client.post(
            self.campaign_url,
            self.campaign_payload(offer_ids=[self.offer.pk, second_offer.pk]),
            format='json',
        )
        campaign_id = created.data['campaign']['id']
        self.admin_client.patch(
            f'/api/advertising/admin/campaigns/{campaign_id}/',
            {'action': 'approve'},
            format='json',
        )
        campaign_offers = {
            row.trader_offer_id: row
            for row in AdvertisingCampaignOffer.objects.filter(campaign_id=campaign_id)
        }
        seen_offer = campaign_offers[self.offer.pk]
        unseen_offer = campaign_offers[second_offer.pk]
        session_header = {'HTTP_X_ADVERTISING_SESSION': 'rotation-session'}
        self.buyer_client.post(
            '/api/advertising/impressions/',
            {'campaign_offer_ids': [seen_offer.pk]},
            format='json',
            **session_header,
        )

        response = self.buyer_client.get(
            f'/api/advertising/placements/?product={self.public_product.slug}&limit=2',
            **session_header,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)
        self.assertEqual(response.data['results'][0]['campaign_offer_id'], unseen_offer.pk)

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True, ADVERTISING_REQUIRE_APPROVAL=True)
    def test_self_click_and_insufficient_funds_do_not_charge(self):
        self._recharge(amount='100.00', key='small-deposit')
        created = self.owner_client.post(self.campaign_url, self.campaign_payload(), format='json')
        campaign_id = created.data['campaign']['id']
        self.admin_client.patch(
            f'/api/advertising/admin/campaigns/{campaign_id}/',
            {'action': 'approve'},
            format='json',
        )
        campaign_offer = AdvertisingCampaignOffer.objects.get(campaign_id=campaign_id)
        response = self.owner_client.post(
            '/api/advertising/clicks/',
            {'campaign_offer_id': campaign_offer.pk, 'idempotency_key': 'self-click'},
            format='json',
        )
        self.assertEqual(response.data['status'], 'invalid')
        self.assertEqual(response.data['reason'], 'self_click')
        self.assertEqual(AdvertisingWallet.objects.get(trader=self.trader).balance, Decimal('100.00'))
        insufficient = self.buyer_client.post(
            '/api/advertising/clicks/',
            {'campaign_offer_id': campaign_offer.pk, 'idempotency_key': 'insufficient-balance'},
            format='json',
            HTTP_X_ADVERTISING_SESSION='buyer-session-without-funds',
        )
        self.assertEqual(insufficient.data['status'], 'invalid')
        self.assertEqual(insufficient.data['charged_amount'], '0.00')
        self.assertEqual(AdvertisingWallet.objects.get(trader=self.trader).balance, Decimal('100.00'))

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True, ADVERTISING_REQUIRE_APPROVAL=True)
    def test_dashboard_contract_and_admin_suspicious_click_count(self):
        self._recharge()
        created = self.owner_client.post(self.campaign_url, self.campaign_payload(), format='json')
        self.admin_client.patch(
            f'/api/advertising/admin/campaigns/{created.data["campaign"]["id"]}/',
            {'action': 'approve'},
            format='json',
        )
        dashboard = self.owner_client.get(self.dashboard_url)
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('dummy_payments_enabled', dashboard.data['wallet'])
        self.assertTrue(dashboard.data['wallet']['dummy_payments_enabled'])
        self.assertIn('stats', dashboard.data)
        self.assertIn('transactions', dashboard.data)
        admin_list = self.admin_client.get('/api/advertising/admin/campaigns/')
        self.assertEqual(admin_list.status_code, 200)
        self.assertIn('trader_name', admin_list.data['results'][0])
        self.assertIn('suspicious_clicks', admin_list.data['results'][0])
        transactions = self.admin_client.get('/api/advertising/admin/transactions/')
        self.assertEqual(transactions.status_code, 200)
        transaction_payload = transactions.data['results'][0]
        self.assertEqual(transaction_payload['trader']['business_name'], self.trader.business_name)
        self.assertIn('reference', transaction_payload)
        self.assertIn('balance_after', transaction_payload)
        self.assertFalse({'card_number', 'cvv', 'expiry'}.intersection(transaction_payload))

    @override_settings(DEBUG=True, PAYMENT_MODE='dummy', ADVERTISING_ENABLED=True)
    def test_admin_adjustment_is_audited_and_cannot_make_balance_negative(self):
        response = self.admin_client.post(
            '/api/advertising/admin/wallet-adjustments/',
            {
                'trader_uuid': str(self.trader.uuid),
                'amount': '250.00',
                'reason': 'Approved billing correction',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='adjustment-one',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AdvertisingWalletTransaction.objects.get().reason, 'Approved billing correction')
        duplicate = self.admin_client.post(
            '/api/advertising/admin/wallet-adjustments/',
            {
                'trader_uuid': str(self.trader.uuid),
                'amount': '250.00',
                'reason': 'Approved billing correction',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='adjustment-one',
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.data['duplicate'])
        self.assertEqual(AdvertisingWalletTransaction.objects.count(), 1)
        rejected = self.admin_client.post(
            '/api/advertising/admin/wallet-adjustments/',
            {
                'trader_uuid': str(self.trader.uuid),
                'amount': '-251.00',
                'reason': 'Would overdraw',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='adjustment-two',
        )
        self.assertEqual(rejected.status_code, 409)

    @override_settings(ADVERTISING_ENABLED=False)
    def test_public_placements_are_disabled_by_server_setting(self):
        response = APIClient().get('/api/advertising/placements/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'results': []})

    def test_ledger_entries_are_immutable(self):
        response = self._recharge()
        self.assertEqual(response.status_code, 201)
        entry = AdvertisingWalletTransaction.objects.get()
        entry.reason = 'tampered'
        with self.assertRaises(ValueError):
            entry.save()
        with self.assertRaises(ValueError):
            entry.delete()
