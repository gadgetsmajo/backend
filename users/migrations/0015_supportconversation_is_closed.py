from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0014_emailmfachallenge_device_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='supportconversation',
            name='is_closed',
            field=models.BooleanField(default=False),
        ),
    ]
