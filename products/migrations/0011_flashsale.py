from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0010_product_extra_fields_productimage'),
    ]

    operations = [
        migrations.CreateModel(
            name='FlashSale',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('flash_price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('ends_at', models.DateTimeField()),
                ('stock_limit', models.PositiveIntegerField(default=0)),
                ('stock_sold', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='flash_sales', to='products.product')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
