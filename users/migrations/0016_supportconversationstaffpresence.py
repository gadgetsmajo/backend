import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('users', '0015_supportconversation_is_closed'),
    ]

    operations = [
        migrations.CreateModel(
            name='SupportConversationStaffPresence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_joined_at', models.DateTimeField(blank=True, null=True)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='staff_presence', to='users.supportconversation')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='support_conversation_presence', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='supportconversationstaffpresence',
            constraint=models.UniqueConstraint(fields=('conversation', 'staff'), name='unique_support_staff_presence'),
        ),
    ]
