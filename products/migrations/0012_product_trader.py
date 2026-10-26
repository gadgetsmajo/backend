import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0011_flashsale'),
        ('traders', '0004_traderproduct_extra_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='trader',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='store_products',
                to='traders.traderapplication',
            ),
        ),
    ]
