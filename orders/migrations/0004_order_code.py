from django.db import migrations, models
import django.utils.crypto


def backfill_codes(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    used = set()
    for order in Order.objects.filter(code=''):
        while True:
            code = django.utils.crypto.get_random_string(8, 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
            if code not in used:
                used.add(code)
                order.code = code
                order.save(update_fields=['code'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_order_delivery_address_order_note_order_phone'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='code',
            field=models.CharField(default='', editable=False, max_length=8),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='order',
            name='code',
            field=models.CharField(editable=False, max_length=8, unique=True),
        ),
    ]
