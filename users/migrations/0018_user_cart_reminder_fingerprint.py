from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0017_supportconversation_admin_message_alert'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='cart_reminder_fingerprint',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
