import uuid

from django.db import migrations
from django.utils.text import slugify


def create_per_trader_catalog_listings(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    TraderProduct = apps.get_model('traders', 'TraderProduct')
    database = schema_editor.connection.alias

    offers = TraderProduct.objects.using(database).filter(
        catalog_product_id__isnull=False,
    ).select_related('catalog_product', 'trader', 'category').order_by('pk')

    for offer in offers.iterator():
        product = Product.objects.using(database).filter(
            trader_product_id=offer.pk,
        ).first()
        if product is None and offer.listing_product_id:
            candidate = Product.objects.using(database).filter(
                pk=offer.listing_product_id,
                trader_id=offer.trader_id,
                catalog_product_id=offer.catalog_product_id,
                trader_product__isnull=True,
                is_catalog_anchor=False,
            ).first()
            if candidate:
                product = candidate

        references = offer.catalog_image_references or offer.catalog_product.image_references or []
        values = {
            'name': offer.name,
            'category': offer.category,
            'brand': offer.brand,
            'condition': offer.condition,
            'tags': offer.tags,
            'specifications': offer.specifications,
            'price': offer.price,
            'original_price': offer.original_price,
            'short_description': offer.short_description or offer.description,
            'long_description': offer.long_description,
            'image': offer.image or (references[0] if references else None),
            'delivery_fee': offer.delivery_fee,
            'stock': offer.stock,
            'is_active': offer.is_active,
            'review_status': offer.review_status,
            'review_note': offer.review_note,
            'trader': offer.trader,
            'trader_product': offer,
            'catalog_product': offer.catalog_product,
            'is_catalog_anchor': False,
            'is_featured': offer.is_featured,
            'is_new_deal': offer.is_new_deal,
        }
        if product is None:
            product_uuid = uuid.uuid4()
            product = Product.objects.using(database).create(
                uuid=product_uuid,
                slug=f'{slugify(offer.name) or "product"}-{product_uuid.hex[:12]}',
                **values,
            )
        else:
            for field, value in values.items():
                setattr(product, field, value)
            product.save(update_fields=tuple(values))

        TraderProduct.objects.using(database).filter(pk=offer.pk).update(
            listing_product_id=product.pk,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0029_backfill_approved_catalog_request_offers'),
        ('traders', '0019_traderproduct_listing_product_and_more'),
    ]

    operations = [
        migrations.RunPython(
            create_per_trader_catalog_listings,
            migrations.RunPython.noop,
        ),
    ]
