from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0010_order_subtotal_delivery_fee'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payment',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                    ('invalid', 'Invalid'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
