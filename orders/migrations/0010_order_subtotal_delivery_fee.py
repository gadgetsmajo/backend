from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0009_payment'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='subtotal',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_fee',
            field=models.DecimalField(decimal_places=2, default=5000, max_digits=10),
        ),
    ]
