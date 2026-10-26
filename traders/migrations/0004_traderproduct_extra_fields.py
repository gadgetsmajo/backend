import cloudinary.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('traders', '0003_traderproduct_image'),
        ('products', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='traderproduct',
            name='short_description',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='long_description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='original_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='delivery_fee',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='products.category'),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='is_featured',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='is_new_deal',
            field=models.BooleanField(default=False),
        ),
    ]
