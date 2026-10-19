from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_support_chat'),
    ]

    operations = [
        migrations.AddField(
            model_name='supportconversation',
            name='customer_typing_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='supportconversation',
            name='staff_typing_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]