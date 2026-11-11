from django.db import migrations
from django.db.models import Q


def relink_unowned_trader_products(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    TraderProduct = apps.get_model('traders', 'TraderProduct')
    database = schema_editor.connection.alias
    products = Product.objects.using(database)

    for trader_product in TraderProduct.objects.using(database).iterator():
        if products.filter(trader_product_id=trader_product.pk).exists():
            continue

        candidates = list(
            products.filter(
                trader_id=trader_product.trader_id,
                trader_product__isnull=True,
                name__iexact=trader_product.name,
            ).order_by('pk').values_list('pk', flat=True)[:2]
        )
        if len(candidates) > 1:
            continue

        if len(candidates) == 1:
            product_id = candidates[0]
        elif trader_product.image:
            image = str(trader_product.image)
            image_matches = []
            for product in products.filter(
                trader_product__isnull=True,
            ).filter(
                Q(trader_id=trader_product.trader_id) | Q(trader_id__isnull=True)
            ).order_by('pk').iterator():
                if product.image and str(product.image) == image:
                    image_matches.append(product.pk)
                    if len(image_matches) > 1:
                        break
            if len(image_matches) != 1:
                continue
            product_id = image_matches[0]
        else:
            continue

        products.filter(pk=product_id).update(
            trader_product_id=trader_product.pk,
            trader_id=trader_product.trader_id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0017_flexible_product_catalog'),
        ('traders', '0014_traderproduct_configurable_details'),
    ]

    operations = [
        migrations.RunPython(
            relink_unowned_trader_products,
            migrations.RunPython.noop,
        ),
    ]
