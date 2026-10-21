from datetime import datetime, timedelta
from .models import Notification


def _already_sent(user, title, within_minutes=10):
    """Prevent duplicate notifications within a time window."""
    cutoff = datetime.utcnow() - timedelta(minutes=within_minutes)
    from django.utils import timezone
    cutoff = timezone.now() - timedelta(minutes=within_minutes)
    return Notification.objects.filter(
        user=user, title=title, created_at__gte=cutoff
    ).exists()


def notify(user, type, title, message, device_name='', dedupe_minutes=10):
    if _already_sent(user, title, dedupe_minutes):
        return None
    
    notification = Notification.objects.create(
        user=user, type=type, title=title,
        message=message, device_name=device_name,
    )
    
    # Send push notification to subscribed devices
    try:
        from .push_utils import send_push_to_user
        unread_count = Notification.objects.filter(user=user, is_read=False).count()
        send_push_to_user(
            user=user,
            title=title,
            body=message,
            badge_count=unread_count,
            data={
                'notification_id': notification.id,
                'type': type,
                'url': '/EducFarm/notifications',
            }
        )
    except Exception as e:
        # Log but don't fail if push fails
        print(f'Error sending push notification: {e}')
    
    return notification


# ── Specific notification helpers ─────────────────────────

def pump_starting_soon(user, pump_time, device_name=''):
    return notify(
        user, 'pump',
        '⏰ Pump Starting Soon',
        f'Irrigation pump is scheduled to start at {pump_time} — in about 4 minutes. Make sure the water supply is ready.',
        device_name, dedupe_minutes=5,
    )


def pump_failure(user, device_name=''):
    return notify(
        user, 'sensor',
        '🚨 Pump Failure Detected',
        'The irrigation pump failed to start or stopped unexpectedly. Check the pump connection and power supply.',
        device_name, dedupe_minutes=30,
    )


def no_water_in_tank(user, device_name=''):
    return notify(
        user, 'water',
        '💧 Water Tank Empty',
        'The water tank level is critically low or empty. Irrigation cannot proceed until the tank is refilled.',
        device_name, dedupe_minutes=60,
    )


def irrigation_skipped(user, reason='', device_name=''):
    return notify(
        user, 'pump',
        '⏭️ Irrigation Skipped',
        f"Today's irrigation was skipped. Reason: {reason or 'Weather conditions do not require irrigation.'}",
        device_name, dedupe_minutes=60,
    )


def pump_stopped_manually(user, device_name=''):
    return notify(
        user, 'pump',
        '🛑 Pump Stopped Manually',
        'The irrigation pump was manually stopped before completing the scheduled cycle.',
        device_name, dedupe_minutes=5,
    )


def irrigation_stopped(user, device_name=''):
    return notify(
        user, 'pump',
        '🔴 Irrigation Stopped',
        'Irrigation has been stopped. All scheduled pump cycles for today have been cancelled.',
        device_name, dedupe_minutes=5,
    )


def check_sensor_thresholds(device, reading):
    """Auto-notify when sensor readings cross critical thresholds."""
    user = device.user
    name = device.device_name
    if reading.soil_moisture is not None and reading.soil_moisture < 20:
        notify(user, 'sensor', '🌱 Soil Moisture Critical',
               f'Soil moisture is {reading.soil_moisture:.1f}% — below the critical threshold of 20%. Irrigation recommended.',
               name, dedupe_minutes=30)
    if reading.water_tank is not None and reading.water_tank < 15:
        notify(user, 'water', '💧 Water Tank Low',
               f'Water tank is at {reading.water_tank:.1f}% — nearly empty. Please refill.',
               name, dedupe_minutes=60)
    if reading.temperature is not None and reading.temperature > 35:
        notify(user, 'weather', '🌡️ High Temperature Alert',
               f'Temperature is {reading.temperature:.1f}°C — consider increasing irrigation frequency.',
               name, dedupe_minutes=60)
