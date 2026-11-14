import hashlib
import hmac
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .notifications import notify_advertising_trader, notify_campaign_status
from .models import (
    AdvertisingCampaign,
    AdvertisingCampaignOffer,
    AdvertisingClick,
    AdvertisingPayment,
    AdvertisingWallet,
    AdvertisingWalletTransaction,
)

ZERO = Decimal('0.00')
CENT = Decimal('0.01')
CLICK_COOLDOWN = timedelta(seconds=60)


class PaymentRejected(Exception):
    pass


class PaymentConfigurationError(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class InsufficientFunds(Exception):
    pass


class AdvertisingPaymentProvider:
    provider_name = 'abstract'

    def charge(self, *, amount, card_number, expiry, cvv, cardholder_name):
        raise NotImplementedError


class DummyPaymentProvider(AdvertisingPaymentProvider):
    provider_name = 'dummy'
    test_card_number = '5200000000000114'

    def charge(self, *, amount, card_number, expiry, cvv, cardholder_name):
        if not settings.DEBUG or getattr(settings, 'PAYMENT_MODE', '') != 'dummy':
            raise PaymentConfigurationError('Dummy payments are not enabled.')
        normalized_number = ''.join(char for char in str(card_number) if char.isdigit())
        valid = (
            hmac.compare_digest(normalized_number, self.test_card_number)
            and str(expiry).strip() in ('07/28', '07/2028')
            and hmac.compare_digest(str(cvv).strip(), '123')
            and bool(str(cardholder_name).strip())
        )
        if not valid:
            raise PaymentRejected('The development test card details are invalid.')
        return f'DUMMY-ADV-{secrets.token_hex(8).upper()}'


def get_wallet(trader, *, lock=False):
    wallet, _ = AdvertisingWallet.objects.get_or_create(trader=trader)
    if lock:
        wallet = AdvertisingWallet.objects.select_for_update().get(pk=wallet.pk)
    return wallet


@transaction.atomic
def reconcile_campaign(campaign_id):
    campaign = AdvertisingCampaign.objects.select_for_update().select_related('trader').get(pk=campaign_id)
    previous_status = campaign.status
    daily_auto_paused = (
        campaign.status == AdvertisingCampaign.Status.PAUSED
        and campaign.pause_reason == 'daily_budget_exhausted'
    )
    if campaign.status not in (
        AdvertisingCampaign.Status.ACTIVE,
        AdvertisingCampaign.Status.SCHEDULED,
    ) and not daily_auto_paused:
        return campaign
    today = timezone.localdate()
    reason = ''
    next_status = campaign.status
    if campaign.end_date < today:
        next_status = AdvertisingCampaign.Status.COMPLETED
        reason = 'campaign_ended'
    elif campaign_spend(campaign) >= campaign.total_budget:
        next_status = AdvertisingCampaign.Status.BUDGET_EXHAUSTED
        reason = 'total_budget_exhausted'
    else:
        wallet = get_wallet(campaign.trader)
        if wallet.balance <= ZERO:
            next_status = AdvertisingCampaign.Status.PAUSED
            reason = 'insufficient_balance'
        else:
            for row in campaign.offers.select_related(
                'trader_offer__catalog_product',
                'trader_offer__public_product',
            ):
                valid, eligibility_reason = eligible_offer(row.trader_offer)
                if not valid or row.trader_offer.trader_id != campaign.trader_id or row.catalog_product_id != row.trader_offer.catalog_product_id:
                    next_status = AdvertisingCampaign.Status.PAUSED
                    reason = eligibility_reason or 'offer_mismatch'
                    break
            if not reason and daily_auto_paused:
                spent_today = daily_campaign_spend(campaign, today)
                if spent_today + campaign.max_cpc <= campaign.daily_budget:
                    next_status = AdvertisingCampaign.Status.ACTIVE
                else:
                    reason = 'daily_budget_exhausted'
                    next_status = AdvertisingCampaign.Status.PAUSED
            if not reason and campaign.status == AdvertisingCampaign.Status.SCHEDULED and campaign.start_date <= today:
                next_status = AdvertisingCampaign.Status.ACTIVE
            if not reason and next_status == AdvertisingCampaign.Status.ACTIVE and daily_campaign_spend(campaign, today) + campaign.max_cpc > campaign.daily_budget:
                reason = 'daily_budget_exhausted'
                next_status = AdvertisingCampaign.Status.PAUSED
    if campaign.status != next_status or campaign.pause_reason != reason:
        campaign.status = next_status
        campaign.pause_reason = reason
        campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
        if campaign.status != previous_status:
            notify_campaign_status(campaign)
    return campaign


def _money(value, field_name):
    try:
        amount = Decimal(str(value)).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid amount.')
    if not amount.is_finite():
        raise ValueError(f'{field_name} must be a valid amount.')
    if amount > Decimal('999999999999.99'):
        raise ValueError(f'{field_name} exceeds the supported maximum.')
    return amount


def _payment_result(payment, transaction_record, *, previous_balance=None):
    if previous_balance is None:
        previous_balance = transaction_record.balance_after - payment.amount
    return {
        'payment': {
            'reference': payment.provider_reference,
            'status': payment.status,
            'amount': str(payment.amount),
        },
        'wallet': {
            'previous_balance': str(previous_balance),
            'amount_added': str(payment.amount),
            'balance': str(transaction_record.balance_after),
            'currency': 'UGX',
        },
    }


@transaction.atomic
def recharge_wallet(trader, *, amount, idempotency_key, card_number, expiry, cvv, cardholder_name):
    amount = _money(amount, 'amount')
    if amount <= ZERO:
        raise ValueError('amount must be greater than zero.')
    idempotency_key = str(idempotency_key or '').strip()
    if not idempotency_key or len(idempotency_key) > 100:
        raise ValueError('A valid Idempotency-Key header is required.')

    wallet = get_wallet(trader, lock=True)
    previous_payment = AdvertisingPayment.objects.filter(
        trader=trader,
        idempotency_key=idempotency_key,
    ).first()
    if previous_payment:
        if previous_payment.amount != amount:
            raise IdempotencyConflict('This Idempotency-Key was already used for a different amount.')
        previous_transaction = previous_payment.wallet_transactions.order_by('pk').first()
        if previous_transaction:
            return _payment_result(previous_payment, previous_transaction)

    provider = get_payment_provider()
    provider_reference = provider.charge(
        amount=amount,
        card_number=card_number,
        expiry=expiry,
        cvv=cvv,
        cardholder_name=cardholder_name,
    )
    payment = AdvertisingPayment.objects.create(
        trader=trader,
        provider=provider.provider_name,
        provider_reference=provider_reference,
        idempotency_key=idempotency_key,
        amount=amount,
    )
    new_balance = wallet.balance + amount
    wallet.balance = new_balance
    wallet.save(update_fields=('balance', 'updated_at'))
    ledger_entry = AdvertisingWalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=AdvertisingWalletTransaction.Type.DEPOSIT,
        amount=amount,
        balance_after=new_balance,
        reference=provider_reference,
        idempotency_key=idempotency_key,
        payment=payment,
        reason='Advertising wallet recharge',
    )
    notify_advertising_trader(
        trader,
        title='Advertising wallet recharged',
        body=(
            f'UGX {amount:,.2f} was added to your advertising wallet. '
            f'New balance: UGX {new_balance:,.2f}.'
        ),
    )
    return _payment_result(payment, ledger_entry, previous_balance=new_balance - amount)


def eligible_offer(offer, *, require_public_approval=True):
    trader = offer.trader
    if trader.status != 'approved' or not trader.is_visible or trader.is_closed:
        return False, 'Trader is not eligible to advertise.'
    if not offer.is_active or offer.availability != 'in_stock' or offer.stock <= 0:
        return False, 'Offer is inactive or out of stock.'
    if offer.price <= ZERO:
        return False, 'Offer must have a valid price.'
    catalog = offer.catalog_product
    if not catalog or not catalog.is_active or catalog.review_status != 'approved':
        return False, 'Offer must link to an approved catalog product.'

    public_product = None
    try:
        public_product = offer.public_product
    except ObjectDoesNotExist:
        public_product = None
    if not public_product:
        return False, 'Offer must be linked to a public marketplace product.'
    if require_public_approval:
        if not public_product.is_active or public_product.review_status != 'approved':
            return False, 'Linked public product is not approved or active.'
        if public_product.catalog_product_id and public_product.catalog_product_id != catalog.pk:
            return False, 'Linked public product does not match the catalog product.'

    has_image = bool(
        (public_product and public_product.image)
        or offer.image
        or offer.image_url
        or catalog.image_references
    )
    if not has_image:
        return False, 'Offer must have an image.'
    return True, ''


def campaign_spend(campaign):
    total = campaign.wallet_transactions.filter(
        transaction_type=AdvertisingWalletTransaction.Type.CLICK,
    ).aggregate(value=Sum('amount'))['value'] or ZERO
    return -total


def daily_campaign_spend(campaign, on_date=None):
    on_date = on_date or timezone.localdate()
    start = timezone.make_aware(
        timezone.datetime.combine(on_date, timezone.datetime.min.time())
    )
    end = start + timedelta(days=1)
    total = campaign.wallet_transactions.filter(
        transaction_type=AdvertisingWalletTransaction.Type.CLICK,
        created_at__gte=start,
        created_at__lt=end,
    ).aggregate(value=Sum('amount'))['value'] or ZERO
    return -total


def visitor_hash(request):
    explicit_session = request.headers.get('X-Advertising-Session', '').strip()[:128]
    if explicit_session:
        identity = f'session:{explicit_session}'
    elif getattr(request.user, 'is_authenticated', False):
        identity = f'user:{request.user.pk}'
    else:
        identity = f'ip:{request.META.get("REMOTE_ADDR", "")}|ua:{request.META.get("HTTP_USER_AGENT", "")[:256]}'
    return hmac.new(
        str(settings.SECRET_KEY).encode('utf-8'),
        identity.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def _click_result(click, public_product=None, *, duplicate=False):
    return {
        'status': click.status,
        'slug': public_product.slug if public_product else None,
        'charged_amount': str(ZERO if duplicate else click.charged_amount),
        'reason': click.reason or None,
        'duplicate': duplicate,
    }


@transaction.atomic
def record_click(*, campaign_offer_id, idempotency_key, request):
    idempotency_key = str(idempotency_key or '').strip()
    if not idempotency_key or len(idempotency_key) > 100:
        raise ValueError('A valid idempotency_key is required.')
    campaign_offer = (
        AdvertisingCampaignOffer.objects.select_related(
            'campaign__trader',
            'campaign__trader__user',
            'trader_offer__trader',
            'trader_offer__catalog_product',
            'trader_offer__public_product',
        )
        .filter(pk=campaign_offer_id)
        .first()
    )
    if not campaign_offer:
        raise LookupError('Sponsored placement was not found.')
    campaign = AdvertisingCampaign.objects.select_for_update().get(pk=campaign_offer.campaign_id)
    previous_campaign_status = campaign.status
    campaign_offer = AdvertisingCampaignOffer.objects.select_for_update().select_related(
        'trader_offer__trader', 'trader_offer__catalog_product', 'trader_offer__public_product',
    ).get(pk=campaign_offer.pk)
    key = {'campaign_offer': campaign_offer, 'idempotency_key': idempotency_key}
    existing_click = AdvertisingClick.objects.filter(**key).first()
    if existing_click:
        try:
            public_product = campaign_offer.trader_offer.public_product
        except ObjectDoesNotExist:
            public_product = None
        return _click_result(existing_click, public_product, duplicate=True)

    user = request.user if getattr(request.user, 'is_authenticated', False) else None
    visitor = visitor_hash(request)

    def record_nonbillable(status_value, reason):
        click, _ = AdvertisingClick.objects.get_or_create(
            **key,
            defaults={
                'visitor_hash': visitor,
                'user': user,
                'status': status_value,
                'reason': reason,
            },
        )
        return click

    offer = campaign_offer.trader_offer
    trader = campaign.trader
    is_owner = bool(
        user and (
            trader.user_id == user.pk
            or trader.email.casefold() == (user.email or '').casefold()
        )
    )
    if is_owner:
        click = record_nonbillable(AdvertisingClick.Status.INVALID, 'self_click')
    else:
        recent_click = AdvertisingClick.objects.filter(
            campaign_offer=campaign_offer,
            visitor_hash=visitor,
            status=AdvertisingClick.Status.VALID,
            created_at__gte=timezone.now() - CLICK_COOLDOWN,
        ).exists()
        if recent_click:
            click = record_nonbillable(AdvertisingClick.Status.SUSPICIOUS, 'repeat_click')
        else:
            valid_offer, eligibility_reason = eligible_offer(offer)
            today = timezone.localdate()
            status_reason = ''
            if campaign.status != AdvertisingCampaign.Status.ACTIVE:
                status_reason = 'campaign_not_active'
            elif campaign.start_date > today:
                status_reason = 'campaign_not_started'
            elif campaign.end_date < today:
                campaign.status = AdvertisingCampaign.Status.COMPLETED
                campaign.save(update_fields=('status', 'updated_at'))
                status_reason = 'campaign_ended'
            elif not valid_offer:
                status_reason = eligibility_reason
                campaign.status = AdvertisingCampaign.Status.PAUSED
                campaign.pause_reason = eligibility_reason
                campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
            elif offer.trader_id != trader.pk:
                status_reason = 'offer_trader_mismatch'
            elif campaign_offer.catalog_product_id != offer.catalog_product_id:
                status_reason = 'catalog_product_mismatch'
            wallet = get_wallet(trader, lock=True)
            spent = campaign_spend(campaign)
            spent_today = daily_campaign_spend(campaign, today)
            if not status_reason and spent >= campaign.total_budget:
                campaign.status = AdvertisingCampaign.Status.BUDGET_EXHAUSTED
                campaign.pause_reason = 'total_budget_exhausted'
                campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
                status_reason = 'total_budget_exhausted'
            if not status_reason and spent_today + campaign.max_cpc > campaign.daily_budget:
                status_reason = 'daily_budget_exhausted'
                campaign.status = AdvertisingCampaign.Status.PAUSED
                campaign.pause_reason = status_reason
                campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
            if not status_reason and wallet.balance < campaign.max_cpc:
                campaign.status = AdvertisingCampaign.Status.PAUSED
                campaign.pause_reason = 'insufficient_balance'
                campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
                status_reason = 'insufficient_balance'
            if status_reason:
                click = record_nonbillable(AdvertisingClick.Status.INVALID, status_reason)
            else:
                wallet.balance -= campaign.max_cpc
                wallet.save(update_fields=('balance', 'updated_at'))
                reference = f'CLICK-ADV-{secrets.token_hex(8).upper()}'
                ledger = AdvertisingWalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type=AdvertisingWalletTransaction.Type.CLICK,
                    amount=-campaign.max_cpc,
                    balance_after=wallet.balance,
                    reference=reference,
                    idempotency_key=idempotency_key,
                    campaign=campaign,
                    reason='Sponsored product click',
                    created_by=user,
                )
                click = AdvertisingClick.objects.create(
                    campaign_offer=campaign_offer,
                    idempotency_key=idempotency_key,
                    visitor_hash=visitor,
                    user=user,
                    status=AdvertisingClick.Status.VALID,
                    charged_amount=campaign.max_cpc,
                )
                if spent + campaign.max_cpc >= campaign.total_budget:
                    campaign.status = AdvertisingCampaign.Status.BUDGET_EXHAUSTED
                    campaign.pause_reason = 'total_budget_exhausted'
                    campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
                elif wallet.balance <= ZERO:
                    campaign.status = AdvertisingCampaign.Status.PAUSED
                    campaign.pause_reason = 'insufficient_balance'
                    campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
                elif spent_today + campaign.max_cpc >= campaign.daily_budget:
                    campaign.status = AdvertisingCampaign.Status.PAUSED
                    campaign.pause_reason = 'daily_budget_exhausted'
                    campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
                if ledger.amount != -click.charged_amount:
                    raise IntegrityError('Advertising click ledger amount mismatch.')
    if campaign.status != previous_campaign_status:
        notify_campaign_status(campaign)
    try:
        public_product = offer.public_product
    except ObjectDoesNotExist:
        public_product = None
    return _click_result(click, public_product)


def get_payment_provider():
    mode = getattr(settings, 'PAYMENT_MODE', '')
    if mode == 'dummy' and settings.DEBUG:
        return DummyPaymentProvider()
    raise PaymentConfigurationError('No advertising payment provider is configured.')
