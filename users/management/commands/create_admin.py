from django.core.management.base import BaseCommand
from users.models import User


class Command(BaseCommand):
    help = 'Create or upgrade a superadmin account with all permissions'

    def add_arguments(self, parser):
        parser.add_argument('email',    type=str)
        parser.add_argument('password', type=str)
        parser.add_argument('--name',   type=str, default='Admin')

    def handle(self, *args, **kwargs):
        email    = kwargs['email']
        password = kwargs['password']
        name     = kwargs['name']

        user, created = User.objects.get_or_create(email=email)

        if created:
            user.full_name = name
            user.set_password(password)

        user.is_staff       = True
        user.is_superuser   = True
        user.admin_level    = 'superadmin'
        user.can_manage_users   = True
        user.can_manage_devices = True
        user.can_manage_weather = True
        user.can_manage_system  = True
        user.save()

        action = 'created' if created else 'upgraded'
        self.stdout.write(self.style.SUCCESS(f'Superadmin {action}: {email}'))
