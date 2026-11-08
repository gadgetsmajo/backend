from django.db import migrations


def link_unowned_trader_products(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    TraderProduct = apps.get_model('traders', 'TraderProduct')
    database = schema_editor.connection.alias

    products = Product.objects.using(database)
    trader_products = TraderProduct.objects.using(database).select_related('trader')

    for trader_product in trader_products.iterator():
        if products.filter(trader_product_id=trader_product.pk).exists():
            continue

        candidates = list(
            products.filter(
                trader_id=trader_product.trader_id,
                trader_product__isnull=True,
                name__iexact=trader_product.name,
            ).order_by('pk')[:2]
        )
        if not candidates and trader_product.image:
            unowned_candidates = products.filter(
                trader_id__isnull=True,
                trader_product__isnull=True,
                name__iexact=trader_product.name,
            ).order_by('pk')[:2]
            candidates = [
                product for product in unowned_candidates
                if product.image and str(product.image) == str(trader_product.image)
            ]
        if len(candidates) != 1:
            continue

        product = candidates[0]
        product.trader_product_id = trader_product.pk
        product.trader_id = trader_product.trader_id
        product.name = trader_product.name
        product.short_description = (
            trader_product.short_description or trader_product.description
        )
        product.long_description = trader_product.long_description
        product.price = trader_product.price
        product.original_price = trader_product.original_price
        product.delivery_fee = trader_product.delivery_fee
        product.stock = trader_product.stock
        product.category_id = trader_product.category_id
        product.image = trader_product.image
        product.is_active = trader_product.is_active and trader_product.trader.is_visible
        product.is_featured = trader_product.is_featured
        product.is_new_deal = trader_product.is_new_deal
        product.save(using=database)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0014_link_legacy_trader_products'),
        ('traders', '0013_traderapplication_payout_account_name_and_more'),
    ]

    operations = [
        migrations.RunPython(
            link_unowned_trader_products,
            migrations.RunPython.noop,
        ),
    ]
