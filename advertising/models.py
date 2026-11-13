from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class AdvertisingWallet(models.Model):
    trader = models.OneToOneField(
        'traders.TraderApplication',
        on_delete=models.PROTECT,
        related_name='advertising_wallet',
    )
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='UGX')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name='advertising_wallet_nonnegative'),
        ]

    def __str__(self):
        return f'{self.trader.business_name} advertising wallet'


class AdvertisingCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PENDING_REVIEW = 'pending_review', 'Pending review'
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused'
        BUDGET_EXHAUSTED = 'budget_exhausted', 'Budget exhausted'
        SCHEDULED = 'scheduled', 'Scheduled'
        COMPLETED = 'completed', 'Completed'
        REJECTED = 'rejected', 'Rejected'
        CANCELLED = 'cancelled', 'Cancelled'

    trader = models.ForeignKey(
        'traders.TraderApplication',
        on_delete=models.PROTECT,
        related_name='advertising_campaigns',
    )
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW)
    max_cpc = models.DecimalField(max_digits=12, decimal_places=2)
    daily_budget = models.DecimalField(max_digits=14, decimal_places=2)
    total_budget = models.DecimalField(max_digits=14, decimal_places=2)
    start_date = models.DateField()
    end_date = models.DateField()
    pause_reason = models.CharField(max_length=120, blank=True, default='')
    rejection_reason = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_advertising_campaigns',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=('status', 'start_date', 'end_date'), name='adv_campaign_status_dates'),
            models.Index(fields=('trader', 'status'), name='adv_campaign_trader_status'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(max_cpc__gt=0), name='adv_campaign_cpc_positive'),
            models.CheckConstraint(condition=Q(daily_budget__gt=0), name='adv_campaign_daily_positive'),
            models.CheckConstraint(condition=Q(total_budget__gt=0), name='adv_campaign_total_positive'),
            models.CheckConstraint(condition=Q(end_date__gte=models.F('start_date')), name='adv_campaign_dates_valid'),
        ]

    def __str__(self):
        return self.name


class AdvertisingCampaignOffer(models.Model):
    campaign = models.ForeignKey(AdvertisingCampaign, on_delete=models.CASCADE, related_name='offers')
    trader_offer = models.ForeignKey(
        'traders.TraderProduct',
        on_delete=models.PROTECT,
        related_name='advertising_campaign_offers',
    )
    catalog_product = models.ForeignKey(
        'products.CatalogProduct',
        on_delete=models.PROTECT,
        related_name='advertising_campaign_offers',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('pk',)
        constraints = [
            models.UniqueConstraint(
                fields=('campaign', 'trader_offer'),
                name='adv_campaign_unique_trader_offer',
            ),
        ]
        indexes = [
            models.Index(fields=('trader_offer',), name='adv_campaign_offer_offer'),
        ]

    def clean(self):
        if self.campaign_id and self.trader_offer_id:
            if self.campaign.trader_id != self.trader_offer.trader_id:
                raise ValidationError({'trader_offer': 'Campaign offers must belong to the campaign trader.'})
            if self.catalog_product_id != self.trader_offer.catalog_product_id:
                raise ValidationError({'catalog_product': 'Campaign catalog product must match the selected trader offer.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.campaign.name}: {self.trader_offer.name}'


class AdvertisingPayment(models.Model):
    trader = models.ForeignKey(
        'traders.TraderApplication',
        on_delete=models.PROTECT,
        related_name='advertising_payments',
    )
    provider = models.CharField(max_length=24)
    provider_reference = models.CharField(max_length=100, unique=True)
    idempotency_key = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=20, default='succeeded')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('trader', 'idempotency_key'),
                name='adv_payment_trader_idempotency',
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name='adv_payment_amount_positive'),
        ]

    def __str__(self):
        return self.provider_reference


class AdvertisingWalletTransaction(models.Model):
    class Type(models.TextChoices):
        DEPOSIT = 'deposit', 'Deposit'
        CLICK = 'click', 'Sponsored click'
        ADJUSTMENT = 'adjustment', 'Admin adjustment'

    wallet = models.ForeignKey(
        AdvertisingWallet,
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    transaction_type = models.CharField(max_length=16, choices=Type.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True)
    idempotency_key = models.CharField(max_length=100, blank=True, default='')
    campaign = models.ForeignKey(
        AdvertisingCampaign,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='wallet_transactions',
    )
    payment = models.ForeignKey(
        AdvertisingPayment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='wallet_transactions',
    )
    reason = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='advertising_wallet_transactions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        indexes = [
            models.Index(fields=('wallet', '-created_at'), name='adv_ledger_wallet_created'),
            models.Index(fields=('campaign', 'transaction_type', 'created_at'), name='adv_ledger_campaign_time'),
        ]
        constraints = [
            models.CheckConstraint(condition=~Q(amount=0), name='adv_ledger_amount_nonzero'),
            models.CheckConstraint(condition=Q(balance_after__gte=0), name='adv_ledger_balance_nonnegative'),
            models.UniqueConstraint(
                fields=('wallet', 'idempotency_key'),
                condition=~Q(idempotency_key=''),
                name='adv_ledger_wallet_idempotency',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError('Advertising wallet ledger entries are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Advertising wallet ledger entries are immutable.')

    def __str__(self):
        return f'{self.reference}: {self.amount}'


class AdvertisingImpression(models.Model):
    campaign_offer = models.ForeignKey(
        AdvertisingCampaignOffer,
        on_delete=models.CASCADE,
        related_name='impressions',
    )
    visitor_hash = models.CharField(max_length=64)
    impression_date = models.DateField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='advertising_impressions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('campaign_offer', 'visitor_hash', 'impression_date'),
                name='adv_impression_daily_frequency',
            ),
        ]
        indexes = [
            models.Index(fields=('campaign_offer', 'created_at'), name='adv_impression_offer_time'),
        ]


class AdvertisingClick(models.Model):
    class Status(models.TextChoices):
        VALID = 'valid', 'Valid'
        INVALID = 'invalid', 'Invalid'
        SUSPICIOUS = 'suspicious', 'Suspicious'

    campaign_offer = models.ForeignKey(
        AdvertisingCampaignOffer,
        on_delete=models.PROTECT,
        related_name='clicks',
    )
    idempotency_key = models.CharField(max_length=100)
    visitor_hash = models.CharField(max_length=64)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='advertising_clicks',
    )
    status = models.CharField(max_length=12, choices=Status.choices)
    charged_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    reason = models.CharField(max_length=120, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('campaign_offer', 'idempotency_key'),
                name='adv_click_offer_idempotency',
            ),
        ]
        indexes = [
            models.Index(fields=('campaign_offer', 'visitor_hash', '-created_at'), name='adv_click_visitor_time'),
            models.Index(fields=('campaign_offer', 'status', 'created_at'), name='adv_click_offer_status_time'),
        ]
