import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a superadmin from environment variables ADMIN_EMAIL, ADMIN_NAME, ADMIN_PASSWORD'

    def handle(self, *args, **options):
        email = os.environ.get('ADMIN_EMAIL')
        name = os.environ.get('ADMIN_NAME')
        password = os.environ.get('ADMIN_PASSWORD')

        if not all([email, name, password]):
            self.stdout.write(self.style.WARNING('Skipping: ADMIN_EMAIL, ADMIN_NAME, ADMIN_PASSWORD not set.'))
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f'Admin {email} already exists, skipping.'))
            return

        User.objects.create_superuser(email=email, name=name, password=password)
        self.stdout.write(self.style.SUCCESS(f'Superadmin created: {email}'))
