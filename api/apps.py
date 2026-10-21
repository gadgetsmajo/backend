from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        # Avoid running twice (Django reloader spawns a second process)
        import os
        if os.environ.get('RUN_MAIN') == 'true' or not os.environ.get('RUN_MAIN'):
            _start_device_offline_scheduler()


def _start_device_offline_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _mark_stale_devices_offline,
            trigger=IntervalTrigger(minutes=5),
            id='device_offline_check',
            replace_existing=True,
        )
        scheduler.start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning('APScheduler failed to start: %s', e)


def _mark_stale_devices_offline():
    try:
        from django.utils import timezone
        from datetime import timedelta
        from .models import Device

        cutoff = timezone.now() - timedelta(minutes=10)
        updated = Device.objects.filter(status='Online', last_seen__lt=cutoff).update(status='Offline')
        if updated:
            import logging
            logging.getLogger(__name__).info('Marked %d device(s) Offline (no data > 10 min)', updated)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error('device_offline_check error: %s', e)
