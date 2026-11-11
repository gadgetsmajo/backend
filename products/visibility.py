from django.db.models import Q


def public_marketplace_product_filter(product_prefix=''):
    trader_path = f'{product_prefix}trader'
    linked_trader_path = f'{product_prefix}trader_product__trader'

    return (
        Q(**{
            f'{trader_path}__isnull': True,
            f'{product_prefix}trader_product__isnull': True,
        })
        | (
            Q(**{
                f'{trader_path}__status': 'approved',
                f'{trader_path}__is_visible': True,
                f'{trader_path}__is_closed': False,
            })
        )
        | (
            Q(**{
                f'{linked_trader_path}__status': 'approved',
                f'{linked_trader_path}__is_visible': True,
                f'{linked_trader_path}__is_closed': False,
            })
        )
    )
