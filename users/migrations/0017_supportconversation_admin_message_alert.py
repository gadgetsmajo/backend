from django.db import migrations, models


def mark_existing_conversations_notified(apps, schema_editor):
    SupportConversation = apps.get_model('users', 'SupportConversation')
    SupportConversation.objects.all().update(admin_new_message_alert_sent=True)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0016_supportconversationstaffpresence'),
    ]

    operations = [
        migrations.AddField(
            model_name='supportconversation',
            name='admin_new_message_alert_sent',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            mark_existing_conversations_notified,
            migrations.RunPython.noop,
        ),
    ]
