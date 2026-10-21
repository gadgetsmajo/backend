from django.core.management.base import BaseCommand, CommandError
from api.models import Device
from users.models import User


class Command(BaseCommand):
    help = 'Seed a test device for a specific user (multi-tenant safe)'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, required=True, help='Email of the user to assign the device to')

    def handle(self, *args, **kwargs):
        email = kwargs['email']
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f'No user found with email: {email}')

        device, created = Device.objects.get_or_create(
            device_id='EF-93B1A4F3',
            defaults={
                'user':             user,
                'secret_key':       'fcc9b34121dc3bb5345c7cb1412cb4626ce524c1a730dbcb46244ce0aa2ce816',
                'device_name':      'EducFarm Device',
                'pairing_code':     'GX92A7',
                'activation_token': 'TEST-ABC123',
                'is_paired':        False,
                'status':           'Offline',
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(
                f'Device created for {email}:\n'
                f'  Device ID:    EF-93B1A4F3\n'
                f'  Pairing Code: GX92A7\n'
                f'  Secret Key:   fcc9b34121dc3bb5345c7cb1412cb4626ce524c1a730dbcb46244ce0aa2ce816'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'Device already exists (owned by {device.user.email}):\n'
                f'  Device ID:    {device.device_id}\n'
                f'  Pairing Code: {device.pairing_code}'
            ))
