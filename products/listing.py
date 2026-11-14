from collections import deque

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F, IntegerField, Value, Window
from django.db.models.functions import Coalesce
from django.db.models.functions.window import RowNumber


def _product_identity(product):
    if product.catalog_product_id:
        return ('catalog', product.catalog_product_id)
    return ('product', product.pk)


def _seller_identity(product):
    seller_id = product.trader_id
    if seller_id is None and product.trader_product_id:
        try:
            seller_id = product.trader_product.trader_id
        except ObjectDoesNotExist:
            seller_id = None
    return ('trader', seller_id) if seller_id is not None else ('unowned', 0)


def diversify_items(items, product_getter=lambda item: item):
    unique = {}
    identity_order = []
    for item in items:
        product = product_getter(item)
        identity = _product_identity(product)
        if identity not in unique:
            unique[identity] = item
            identity_order.append(identity)
        else:
            current_product = product_getter(unique[identity])
            if (
                _seller_identity(product)[0] == 'trader'
                and _seller_identity(current_product)[0] != 'trader'
            ):
                unique[identity] = item

    seller_groups = {}
    for identity in identity_order:
        item = unique[identity]
        product = product_getter(item)
        seller_groups.setdefault(_seller_identity(product), deque()).append(item)

    diversified = []
    while seller_groups:
        for seller in list(seller_groups):
            diversified.append(seller_groups[seller].popleft())
            if not seller_groups[seller]:
                del seller_groups[seller]
    return diversified


def diversify_product_queryset(queryset, order_fields):
    window_ordering = [
        F(field[1:]).desc() if field.startswith('-') else F(field).asc()
        for field in order_fields
    ]
    seller_bucket = Coalesce(
        'trader_id',
        'trader_product__trader_id',
        Value(0),
        output_field=IntegerField(),
    )
    return queryset.annotate(
        _listing_seller_rank=Window(
            expression=RowNumber(),
            partition_by=[seller_bucket],
            order_by=window_ordering,
        ),
    ).order_by('_listing_seller_rank', *order_fields)
