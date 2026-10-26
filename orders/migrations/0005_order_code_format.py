import random
from django.db import migrations, models
import django.utils.crypto


def reformat_codes(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    used = set()
    for order in Order.objects.all():
        while True:
            numeric = ''.join([str(random.randint(0, 9)) for _ in range(8)])
            suffix = django.utils.crypto.get_random_string(5, 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
            code = f'{numeric}-{suffix}'
            if code not in used:
                used.add(code)
                order.code = code
                order.save(update_fields=['code'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_order_code'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='code',
            field=models.CharField(editable=False, max_length=14, unique=True),
        ),
        migrations.RunPython(reformat_codes, migrations.RunPython.noop),
    ]
