from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from settings_app.models import PlatformSettings
from .models import TraderApplication, TraderEarning


ZERO = Decimal('0.00')


def record_paid_order_earnings(order):
    settings = PlatformSettings.get()
    available_at = timezone.now() + timedelta(days=settings.payout_hold_days)
    order_items = order.items.select_related(
        'product__trader',
        'product__trader_product__trader',
    )
    for item in order_items:
        if not item.product:
            continue
        trader = item.product.trader
        if trader is None and item.product.trader_product_id:
            trader = item.product.trader_product.trader
        if trader is None or item.seller_price is None:
            continue

        TraderEarning.objects.get_or_create(
            order_item=item,
            defaults={
                'trader': trader,
                'order': order,
                'order_code': order.code,
                'product_name': item.product.name,
                'quantity': item.quantity,
                'listed_unit_price': item.seller_price,
                'seller_amount': item.seller_price * item.quantity,
                'commission_pct': item.platform_commission_pct,
                'commission_amount': item.platform_commission,
                'available_at': available_at,
            },
        )


def eligible_earnings(trader):
    return TraderEarning.objects.filter(
        trader=trader,
        status='active',
    ).filter(
        Q(order__isnull=True)
        | (
            ~Q(order__status='cancelled')
            & (
                Q(order__return_request__isnull=True)
                | Q(order__return_request__status='rejected')
            )
        )
    )


def wallet_summary(trader, now=None):
    now = now or timezone.now()
    earnings = eligible_earnings(trader)
    locked = earnings.filter(available_at__gt=now).aggregate(total=Sum('seller_amount'))['total'] or ZERO
    matured = earnings.filter(available_at__lte=now).aggregate(total=Sum('seller_amount'))['total'] or ZERO
    total_earned = earnings.aggregate(total=Sum('seller_amount'))['total'] or ZERO
    reserved = trader.withdrawals.exclude(status='rejected').aggregate(total=Sum('amount'))['total'] or ZERO
    pending = trader.withdrawals.filter(status__in=('requested', 'processing')).aggregate(
        total=Sum('amount')
    )['total'] or ZERO
    next_release = earnings.filter(available_at__gt=now).order_by('available_at').values_list(
        'available_at', flat=True
    ).first()
    return {
        'total_earned': total_earned,
        'locked_balance': locked,
        'pending_withdrawal': pending,
        'available_balance': max(ZERO, matured - reserved),
        'next_release_at': next_release,
    }


@transaction.atomic
def reverse_order_earnings(order):
    TraderEarning.objects.filter(order=order, status='active').update(status='reversed')
