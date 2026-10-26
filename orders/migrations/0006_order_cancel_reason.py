from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0005_order_code_format'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='cancel_reason',
            field=models.TextField(blank=True, default=''),
            preserve_default=False,
        ),
    ]
