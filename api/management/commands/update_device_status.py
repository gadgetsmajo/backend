"""
Management command to mark devices offline if no data received for 10 minutes.
Run periodically via cron: */5 * * * * python manage.py update_device_status
Or schedule in APScheduler/Celery beat task.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from api.models import Device


class Command(BaseCommand):
    help = 'Mark devices as Offline if no sensor data received in the last 10 minutes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--timeout',
            type=int,
            default=10,
            help='Minutes of inactivity before marking device as Offline (default: 10)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Print details of status changes',
        )

    def handle(self, *args, **options):
        timeout_minutes = options['timeout']
        verbose = options['verbose']
        
        cutoff_time = timezone.now() - timedelta(minutes=timeout_minutes)
        
        # Find online devices with no recent data
        offline_devices = Device.objects.filter(
            status='Online',
            last_seen__lt=cutoff_time,
        )
        
        count = offline_devices.count()
        
        if count > 0:
            offline_devices.update(status='Offline')
            if verbose:
                for device in offline_devices:
                    self.stdout.write(
                        self.style.WARNING(
                            f'  ✗ {device.device_name} ({device.device_id}) '
                            f'— no data since {device.last_seen}'
                        )
                    )
            self.stdout.write(
                self.style.SUCCESS(f'✓ Marked {count} device(s) as Offline')
            )
        else:
            if verbose:
                self.stdout.write(self.style.SUCCESS('✓ All online devices are responsive'))
