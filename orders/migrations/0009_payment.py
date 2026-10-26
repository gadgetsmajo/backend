from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0008_alter_order_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pesapal_order_tracking_id', models.CharField(max_length=100, unique=True)),
                ('merchant_reference', models.CharField(blank=True, max_length=100)),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('currency', models.CharField(default='UGX', max_length=10)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('completed', 'Completed'), ('failed', 'Failed'), ('invalid', 'Invalid')], default='pending', max_length=20)),
                ('payment_method', models.CharField(blank=True, max_length=100)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('order', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='payment', to='orders.order')),
            ],
        ),
    ]
