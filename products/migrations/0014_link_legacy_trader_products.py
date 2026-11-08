from django.db import migrations


def link_legacy_trader_products(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    TraderProduct = apps.get_model('traders', 'TraderProduct')
    database = schema_editor.connection.alias

    for trader_product in TraderProduct.objects.using(database).select_related('trader').iterator():
        if Product.objects.using(database).filter(trader_product_id=trader_product.pk).exists():
            continue

        candidates = list(
            Product.objects.using(database).filter(
                trader_id=trader_product.trader_id,
                trader_product__isnull=True,
                name__iexact=trader_product.name,
            ).order_by('pk').values_list('pk', flat=True)[:2]
        )
        if len(candidates) != 1:
            continue

        public_product = Product.objects.using(database).get(pk=candidates[0])
        public_product.trader_product_id = trader_product.pk
        public_product.name = trader_product.name
        public_product.short_description = (
            trader_product.short_description or trader_product.description
        )
        public_product.long_description = trader_product.long_description
        public_product.price = trader_product.price
        public_product.original_price = trader_product.original_price
        public_product.delivery_fee = trader_product.delivery_fee
        public_product.stock = trader_product.stock
        public_product.category_id = trader_product.category_id
        public_product.image = trader_product.image
        public_product.is_active = trader_product.is_active and trader_product.trader.is_visible
        public_product.is_featured = trader_product.is_featured
        public_product.is_new_deal = trader_product.is_new_deal
        public_product.save(using=database)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0013_add_trader_product_fk'),
        ('traders', '0007_traderinventoryitem_traderstockmovement'),
    ]

    operations = [
        migrations.RunPython(
            link_legacy_trader_products,
            migrations.RunPython.noop,
        ),
    ]
