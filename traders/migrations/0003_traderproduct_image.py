import cloudinary.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('traders', '0002_traderapplication_uuid_traderexpense_traderproduct_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='traderproduct',
            name='image',
            field=cloudinary.models.CloudinaryField('image', blank=True, folder='trader_products/', null=True),
        ),
    ]
