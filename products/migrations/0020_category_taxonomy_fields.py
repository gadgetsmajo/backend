from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0019_create_missing_trader_public_products'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='category',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='category',
            name='position',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name='category',
            options={'ordering': ('position', 'name'), 'verbose_name_plural': 'categories'},
        ),
    ]
