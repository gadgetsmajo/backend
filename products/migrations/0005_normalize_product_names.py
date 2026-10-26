import uuid

from django.db import migrations
from django.utils.text import slugify


def normalize_product_names(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    for product in Product.objects.all().iterator():
        product.name = product.name.strip().title()
        if not getattr(product, 'uuid', None):
            product.uuid = uuid.uuid4()
        product.slug = f'{slugify(product.name)}-{product.uuid.hex[:12]}'
        product.save(update_fields=['name', 'uuid', 'slug'])


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0004_product_uuid_slug'),
    ]

    operations = [
        migrations.RunPython(normalize_product_names, migrations.RunPython.noop),
    ]