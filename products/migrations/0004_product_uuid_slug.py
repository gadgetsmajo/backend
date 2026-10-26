import uuid

from django.db import migrations, models
from django.utils.text import slugify


def populate_product_slugs(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    for product in Product.objects.all().iterator():
        if not product.uuid:
            product.uuid = uuid.uuid4()
        product.slug = f'{slugify(product.name)}-{product.uuid.hex[:12]}'
        product.save(update_fields=['uuid', 'slug'])


def drop_slug_index(apps, schema_editor):
    schema_editor.execute(
        'DROP INDEX IF EXISTS products_product_slug_70d3148d_like;'
    )
    schema_editor.execute(
        'DROP INDEX IF EXISTS products_product_slug_key;'
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('products', '0003_category_image'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE products_product ADD COLUMN uuid TEXT;
                        ALTER TABLE products_product ADD COLUMN slug VARCHAR(320);
                    """,
                    reverse_sql="""
                        ALTER TABLE products_product DROP COLUMN uuid;
                        ALTER TABLE products_product DROP COLUMN slug;
                    """,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='product',
                    name='uuid',
                    field=models.UUIDField(editable=False, null=True),
                ),
                migrations.AddField(
                    model_name='product',
                    name='slug',
                    field=models.SlugField(blank=True, max_length=320, null=True),
                ),
                migrations.AlterField(
                    model_name='product',
                    name='slug',
                    field=models.SlugField(blank=True, max_length=320, unique=True),
                ),
                migrations.AlterField(
                    model_name='product',
                    name='uuid',
                    field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
            ],
        ),
    ]
