from django.db import migrations


def repair_fashion_category_collision(apps, schema_editor):
    Category = apps.get_model('products', 'Category')
    database = schema_editor.connection.alias

    department, _ = Category.objects.using(database).update_or_create(
        slug='fashion-accessories',
        defaults={
            'name': 'Fashion & Accessories',
            'description': 'Shop fashion & accessories products.',
            'parent_id': None,
            'is_active': True,
            'position': 32,
        },
    )
    Category.objects.using(database).update_or_create(
        slug='fashion-accessories-fashion-accessories',
        defaults={
            'name': 'Fashion Accessories',
            'parent_id': department.pk,
            'is_active': True,
            'position': 44,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0021_seed_marketplace_taxonomy'),
    ]

    operations = [
        migrations.RunPython(repair_fashion_category_collision, migrations.RunPython.noop),
    ]
