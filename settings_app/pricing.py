from decimal import Decimal, ROUND_HALF_UP

from .models import PlatformSettings


def platform_commission_amount(price, platform_settings=None):
    platform_settings = platform_settings or PlatformSettings.get()
    return (Decimal(price) * platform_settings.commission / Decimal('100')).quantize(
        Decimal('0.01'),
        rounding=ROUND_HALF_UP,
    )


def price_with_platform_charges(price, platform_settings=None):
    platform_settings = platform_settings or PlatformSettings.get()
    multiplier = (
        Decimal('1') + platform_settings.commission / Decimal('100')
    ) * (
        Decimal('1') + platform_settings.vat / Decimal('100')
    )
    return (Decimal(price) * multiplier).quantize(
        Decimal('0.01'),
        rounding=ROUND_HALF_UP,
    )
