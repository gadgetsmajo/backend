from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0006_order_cancel_reason'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceRating',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('overall', models.PositiveSmallIntegerField()),
                ('areas', models.JSONField(default=list)),
                ('area_ratings', models.JSONField(default=dict)),
                ('comment', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('order', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='service_rating', to='orders.order')),
            ],
        ),
    ]
