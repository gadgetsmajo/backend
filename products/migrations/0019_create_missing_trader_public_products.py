import uuid

from django.db import migrations
from django.utils.text import slugify


def create_missing_trader_public_products(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    TraderProduct = apps.get_model('traders', 'TraderProduct')
    database = schema_editor.connection.alias

    for trader_product in TraderProduct.objects.using(database).iterator():
        if Product.objects.using(database).filter(trader_product_id=trader_product.pk).exists():
            continue

        product_uuid = uuid.uuid4()
        name = trader_product.name.strip().title()
        Product.objects.using(database).create(
            uuid=product_uuid,
            name=name,
            slug=f'{slugify(name)}-{product_uuid.hex[:12]}',
            category_id=trader_product.category_id,
            brand=trader_product.brand,
            condition=trader_product.condition,
            tags=trader_product.tags,
            specifications=trader_product.specifications,
            price=trader_product.price,
            original_price=trader_product.original_price,
            short_description=trader_product.short_description or trader_product.description,
            long_description=trader_product.long_description,
            image=trader_product.image,
            delivery_fee=trader_product.delivery_fee,
            stock=trader_product.stock,
            is_active=False,
            review_status='pending_review',
            trader_id=trader_product.trader_id,
            trader_product_id=trader_product.pk,
            is_featured=trader_product.is_featured,
            is_new_deal=trader_product.is_new_deal,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0018_relink_unowned_trader_products'),
        ('traders', '0014_traderproduct_configurable_details'),
    ]

    operations = [
        migrations.RunPython(
            create_missing_trader_public_products,
            migrations.RunPython.noop,
        ),
    ]
