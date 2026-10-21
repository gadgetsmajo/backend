from django.db import models
from users.models import User


class Device(models.Model):
    STATUS_CHOICES = [('Online', 'Online'), ('Offline', 'Offline')]

    user              = models.ForeignKey(User, on_delete=models.CASCADE, related_name='devices')
    device_id         = models.CharField(max_length=100, unique=True)
    secret_key        = models.CharField(max_length=255)
    device_name       = models.CharField(max_length=150)
    pairing_code      = models.CharField(max_length=20, unique=True)  # e.g., GX92A7
    activation_token  = models.CharField(max_length=50, blank=True)   # Temporary test token
    is_paired         = models.BooleanField(default=False)
    crop_type         = models.CharField(max_length=100, blank=True)
    soil_type         = models.CharField(max_length=100, blank=True)
    status            = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Offline')
    last_seen         = models.DateTimeField(null=True, blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    paired_at         = models.DateTimeField(null=True, blank=True)
    wifi_ssid         = models.CharField(max_length=64, blank=True, default='')
    wifi_password     = models.CharField(max_length=64, blank=True, default='')
    wifi_pending      = models.BooleanField(default=False)  # True = hardware must fetch new creds

    def __str__(self):
        return f'{self.device_name} ({self.device_id})'


class FarmSettings(models.Model):
    SOIL_CHOICES = [
        ('Sandy',      'Sandy'),
        ('Clay',       'Clay'),
        ('Silt',       'Silt'),
        ('Loam',       'Loam'),
        ('Sandy Loam', 'Sandy Loam'),
        ('Clay Loam',  'Clay Loam'),
        ('Peat',       'Peat'),
        ('Chalk',      'Chalk'),
    ]

    user                  = models.OneToOneField(User, on_delete=models.CASCADE, related_name='farm_settings')
    soil_type             = models.CharField(max_length=50, choices=SOIL_CHOICES, blank=True)
    plant_type            = models.CharField(max_length=100, blank=True)
    moisture_min          = models.FloatField(default=40.0)
    moisture_max          = models.FloatField(default=70.0)
    moisture_critical_low = models.FloatField(default=20.0)
    irrigation_duration   = models.PositiveIntegerField(default=30, help_text='Minutes per irrigation cycle')
    notes                 = models.TextField(blank=True)
    weather_lat           = models.FloatField(null=True, blank=True)
    weather_lon           = models.FloatField(null=True, blank=True)
    weather_location_name = models.CharField(max_length=200, blank=True, default='')
    # Admin-set location — takes priority over user location, never overwritten by user
    admin_weather_lat           = models.FloatField(null=True, blank=True)
    admin_weather_lon           = models.FloatField(null=True, blank=True)
    admin_weather_location_name = models.CharField(max_length=200, blank=True, default='')
    updated_at            = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.email} — {self.plant_type or "No plant set"}'


class SensorReading(models.Model):
    device     = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='readings')
    soil_moisture  = models.FloatField(null=True, blank=True)
    temperature    = models.FloatField(null=True, blank=True)
    humidity       = models.FloatField(null=True, blank=True)
    water_tank     = models.FloatField(null=True, blank=True)
    pump_status    = models.CharField(max_length=20, default='Off')
    irrig_cycles   = models.PositiveIntegerField(default=0)
    gps_lat        = models.FloatField(null=True, blank=True)
    gps_lon        = models.FloatField(null=True, blank=True)
    gps_place      = models.CharField(max_length=200, blank=True, default='')
    recorded_at    = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['device', '-recorded_at'], name='device_recorded_at_idx'),
        ]

    def __str__(self):
        return f'{self.device.device_name} @ {self.recorded_at}'


class PumpCommand(models.Model):
    """Separate model for pump control events — keeps sensor history clean."""
    STATUS_CHOICES = [('On', 'On'), ('Off', 'Off'), ('Auto', 'Auto'), ('Wake', 'Wake')]
    
    device        = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='pump_commands')
    command       = models.CharField(max_length=10, choices=STATUS_CHOICES)
    issued_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='pump_commands')
    issued_at     = models.DateTimeField(auto_now_add=True, db_index=True)
    acknowledged  = models.BooleanField(default=False)  # True once hardware has polled this command
    
    class Meta:
        ordering = ['-issued_at']
        indexes = [
            models.Index(fields=['device', '-issued_at'], name='pump_cmd_device_time_idx'),
        ]
    
    def __str__(self):
        return f'{self.device.device_name} pump {self.command} @ {self.issued_at}'


class Notification(models.Model):
    TYPE_CHOICES = [
        ('pump',    'Pump'),
        ('weather', 'Weather'),
        ('water',   'Low Water'),
        ('sensor',  'Sensor Failure'),
        ('system',  'System'),
    ]

    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    type        = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system')
    title       = models.CharField(max_length=200)
    message     = models.TextField()
    device_name = models.CharField(max_length=150, blank=True)
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.type}] {self.title}'


class WeatherAccessLog(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weather_logs')
    endpoint   = models.CharField(max_length=50, default='weather')
    lat        = models.FloatField(null=True, blank=True)
    lon        = models.FloatField(null=True, blank=True)
    location   = models.CharField(max_length=200, blank=True)
    success    = models.BooleanField(default=True)
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-accessed_at']

    def __str__(self):
        return f'{self.user} — {self.location} @ {self.accessed_at}'


class DailyAgriLog(models.Model):
    """
    One row per user per day — feeds seasonal learning.
    Written automatically on each weather fetch.
    """
    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agri_logs')
    date          = models.DateField()
    season        = models.CharField(max_length=30, blank=True)
    avg_temp      = models.FloatField(null=True, blank=True)
    avg_moisture  = models.FloatField(null=True, blank=True)
    total_rain_mm = models.FloatField(default=0.0)
    water_used_l  = models.FloatField(default=0.0)
    rain_prob     = models.FloatField(default=0.0)

    class Meta:
        unique_together = ('user', 'date')
        ordering = ['-date']

    def __str__(self):
        return f'{self.user} — {self.date} ({self.season})'


class LocationCache(models.Model):
    search_term  = models.CharField(max_length=255, unique=True, db_index=True)
    display_name = models.TextField()
    latitude     = models.FloatField()
    longitude    = models.FloatField()
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Location Cache'

    def __str__(self):
        return f'{self.search_term} → {self.display_name}'


class PlantProfile(models.Model):
    """
    Admin-managed plant profiles. These override built-in CROP_PROFILES when matched.
    is_active controls whether users can see/select this plant.
    """
    key                  = models.CharField(max_length=100, unique=True)
    label                = models.CharField(max_length=150)
    water_demand_l_day   = models.FloatField(default=5.5)
    stress_temp_high     = models.FloatField(default=32.0)
    stress_moisture_low  = models.FloatField(default=30.0)
    root_depth_factor    = models.FloatField(default=1.0)
    # Season adjust factors stored as JSON: {"long_rains": 0.4, ...}
    season_adjust        = models.JSONField(default=dict)
    is_active            = models.BooleanField(default=True)
    is_builtin           = models.BooleanField(default=False, help_text='True for seeded built-in profiles')
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['label']

    def __str__(self):
        return f'{self.label} ({self.key})'


class PushSubscription(models.Model):
    """Stores browser Web Push subscriptions per user device."""
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint   = models.TextField(unique=True)
    p256dh     = models.TextField()
    auth       = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.email} — {self.endpoint[:60]}'


class SMSSettings(models.Model):
    """Per-user SMS alert configuration — synced to hardware via DeviceSettingsView."""
    user                   = models.OneToOneField(User, on_delete=models.CASCADE, related_name='sms_settings')
    sms_enabled            = models.BooleanField(default=False)
    pump_alerts            = models.BooleanField(default=True)
    weather_alerts         = models.BooleanField(default=True)
    low_water_alerts       = models.BooleanField(default=True)
    sensor_failure_alerts  = models.BooleanField(default=True)
    # JSON list of full phone numbers e.g. ["+256712345678", "+256700000000"]
    phone_numbers          = models.JSONField(default=list)
    # When True, hardware clears its EEPROM phone list and re-fetches once, then backend resets this to False
    phones_dirty           = models.BooleanField(default=True, help_text='True = hardware must re-fetch phone numbers')
    updated_at             = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SMS Settings'

    def __str__(self):
        return f'{self.user.email} — SMS {"on" if self.sms_enabled else "off"}'


class InvestorApplication(models.Model):
    name           = models.CharField(max_length=150)
    organisation   = models.CharField(max_length=200, blank=True)
    email          = models.EmailField()
    phone          = models.CharField(max_length=30, blank=True)
    location       = models.CharField(max_length=200)
    village_parish = models.CharField(max_length=200)
    country        = models.CharField(max_length=100)
    amount         = models.FloatField()
    currency       = models.CharField(max_length=10)
    source         = models.CharField(max_length=100)
    timeline       = models.CharField(max_length=100)
    experience     = models.TextField(blank=True)
    message        = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.currency} {self.amount}'


class BusinessRequest(models.Model):
    name           = models.CharField(max_length=150)
    organisation   = models.CharField(max_length=200, blank=True)
    email          = models.EmailField()
    phone          = models.CharField(max_length=30, blank=True)
    location       = models.CharField(max_length=200)
    village_parish = models.CharField(max_length=200)
    country        = models.CharField(max_length=100)
    request_type   = models.CharField(max_length=100)
    message        = models.TextField()
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.request_type}'


class PartnershipApplication(models.Model):
    name           = models.CharField(max_length=150)
    organisation   = models.CharField(max_length=200, blank=True)
    email          = models.EmailField()
    phone          = models.CharField(max_length=30, blank=True)
    location       = models.CharField(max_length=200)
    village_parish = models.CharField(max_length=200)
    country        = models.CharField(max_length=100)
    partner_type   = models.CharField(max_length=100)
    business_area  = models.CharField(max_length=200, blank=True)
    products       = models.TextField(blank=True)
    markets        = models.CharField(max_length=200, blank=True)
    capacity       = models.TextField(blank=True)
    website        = models.URLField(blank=True)
    interest       = models.TextField()
    message        = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.partner_type}'


class HardwareOrder(models.Model):
    KIT_CHOICES = [
        ('basic',    'Basic Kit — UGX 700,000'),
        ('advanced', 'Advanced Kit — UGX 2,000,000'),
    ]
    STATUS_CHOICES = [
        ('pending',    'Pending'),
        ('confirmed',  'Confirmed'),
        ('shipped',    'Shipped'),
        ('delivered',  'Delivered'),
        ('cancelled',  'Cancelled'),
    ]
    name         = models.CharField(max_length=150)
    phone        = models.CharField(max_length=20)
    email        = models.CharField(max_length=254, blank=True)
    location     = models.CharField(max_length=255, blank=True)
    kit_type     = models.CharField(max_length=20, choices=KIT_CHOICES)
    quantity     = models.PositiveIntegerField(default=1)
    total_ugx    = models.PositiveIntegerField()
    notes        = models.TextField(blank=True)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.kit_type} x{self.quantity} ({self.status})'


class SystemSettings(models.Model):
    """Singleton — only one row ever exists (pk=1)"""
    system_online        = models.BooleanField(default=True)
    maintenance_title    = models.CharField(max_length=200, default='System Maintenance')
    maintenance_message  = models.TextField(default='The system is currently under maintenance. Please check back later.')
    maintenance_sub      = models.CharField(max_length=300, blank=True, default='We apologize for the inconvenience.')
    online_at            = models.DateTimeField(null=True, blank=True, help_text='Scheduled time to go back online')
    updated_at           = models.DateTimeField(auto_now=True)
    updated_by           = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'System Settings'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'System {"Online" if self.system_online else "Offline"}'
