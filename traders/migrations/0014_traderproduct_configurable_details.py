from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('traders', '0013_traderapplication_payout_account_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='traderproduct',
            name='brand',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='condition',
            field=models.CharField(
                choices=[('new', 'New'), ('used', 'Used'), ('refurbished', 'Refurbished')],
                default='new',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='tags',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='traderproduct',
            name='specifications',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
