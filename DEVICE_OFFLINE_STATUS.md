# Device Offline Status Updates

## Overview
Devices are automatically marked as "Offline" when they haven't sent sensor data for more than 10 minutes.

## Setup

### Option 1: Railway Cron Job (Recommended)
Railway supports scheduled jobs via the `railway.toml` file. A cron job is already configured to run every 5 minutes:

```toml
[jobs.update_device_status]
cmd = "python manage.py update_device_status --verbose"
schedule = "*/5 * * * *"
```

### Option 2: Local Development / Cron
Run the management command manually or via system cron:

```bash
# Run immediately
python manage.py update_device_status

# Check with verbose output
python manage.py update_device_status --verbose

# Custom timeout (15 minutes instead of default 10)
python manage.py update_device_status --timeout 15
```

Add to crontab for automatic execution:
```bash
# Run every 5 minutes
*/5 * * * * cd /path/to/EducFarm/backend && python manage.py update_device_status
```

### Option 3: Celery Beat (Future)
When Celery is added, this can run as:
```python
@periodic_task(run_every=crontab(minute='*/5'))
def update_device_offline_status():
    from api.management.commands.update_device_status import Command
    Command().handle(timeout=10, verbose=False)
```

## How It Works

1. Every 5 minutes, the command checks all devices marked as "Online"
2. If a device's `last_seen` is older than 10 minutes, it's marked "Offline"
3. Devices with recent sensor readings remain "Online"

## Monitoring

Check device status via the admin dashboard or API:
```bash
curl https://your-api.railway.app/api/devices/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Devices with `"status": "Offline"` haven't sent data for 10+ minutes.
