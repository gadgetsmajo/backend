from django.contrib import admin
from .models import DailyAgriLog, Device, HardwareOrder

@admin.register(DailyAgriLog)
class DailyAgriLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'season', 'avg_temp', 'avg_moisture', 'total_rain_mm', 'water_used_l']
    list_filter  = ['season']
    ordering     = ['-date']

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display  = ['device_id', 'device_name', 'user', 'secret_key', 'pairing_code', 'status', 'is_paired', 'created_at']
    search_fields = ['device_id', 'device_name', 'secret_key']
    readonly_fields = ['device_id', 'secret_key', 'pairing_code', 'created_at', 'paired_at']
    ordering      = ['-created_at']

@admin.register(HardwareOrder)
class HardwareOrderAdmin(admin.ModelAdmin):
    list_display  = ['id', 'name', 'phone', 'kit_type', 'quantity', 'total_ugx', 'status', 'created_at']
    list_filter   = ['status', 'kit_type']
    search_fields = ['name', 'phone', 'email', 'location']
    list_editable = ['status']
    readonly_fields = ['created_at']
    ordering      = ['-created_at']
