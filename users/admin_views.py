import uuid
import secrets
import string
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db.models import Count, Max, Prefetch
from .models import User
from api.models import Device, SensorReading, FarmSettings, WeatherAccessLog, PlantProfile


class AdminUserListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        # Use annotate to count devices per user (avoids N+1 queries)
        users = User.objects.annotate(
            device_count=Count('devices')
        ).prefetch_related(
            Prefetch('farm_settings', queryset=FarmSettings.objects.all())
        ).order_by('-id')
        
        data = []
        for u in users:
            try:
                fs = u.farm_settings
            except FarmSettings.DoesNotExist:
                fs = None
            data.append({
                'id':           u.id,
                'full_name':    u.full_name,
                'email':        u.email,
                'phone_number': u.phone_number,
                'is_staff':     u.is_staff,
                'is_active':    u.is_active,
                'created_at':   u.created_at,
                'last_seen':    u.last_seen,
                'device_count': u.device_count,
                'avatar_url':   u.avatar_url,
                'profile_updated_at': u.profile_updated_at,
                'soil_type':    fs.soil_type    if fs else '',
                'plant_type':   fs.plant_type   if fs else '',
                'moisture_min': fs.moisture_min if fs else None,
                'moisture_max': fs.moisture_max if fs else None,
                'irrigation_duration': fs.irrigation_duration if fs else None,
                'farm_notes':   fs.notes        if fs else '',
            })
        return Response(data)


class AdminUserDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        fs = FarmSettings.objects.filter(user=user).first()
        devices = Device.objects.filter(user=user).order_by('-created_at')
        notifications = user.notifications.order_by('-created_at')[:20]
        weather_logs = user.weather_logs.order_by('-accessed_at')[:5]

        return Response({
            'id':           user.id,
            'full_name':    user.full_name,
            'email':        user.email,
            'phone_number': user.phone_number,
            'is_staff':     user.is_staff,
            'is_active':    user.is_active,
            'created_at':   user.created_at,
            'last_seen':    user.last_seen,
            'profile_updated_at': user.profile_updated_at,
            'avatar_url':   user.avatar_url,
            'farm_settings': {
                'soil_type':            fs.soil_type            if fs else '',
                'plant_type':           fs.plant_type           if fs else '',
                'moisture_min':         fs.moisture_min         if fs else None,
                'moisture_max':         fs.moisture_max         if fs else None,
                'irrigation_duration':  fs.irrigation_duration  if fs else None,
                'notes':                fs.notes                if fs else '',
                'weather_location':     fs.weather_location_name if fs else '',
                'admin_weather_location': fs.admin_weather_location_name if fs else '',
            } if fs else None,
            'devices': [
                {
                    'id':          d.id,
                    'device_id':   d.device_id,
                    'device_name': d.device_name,
                    'status':      d.status,
                    'is_paired':   d.is_paired,
                    'crop_type':   d.crop_type,
                    'soil_type':   d.soil_type,
                    'last_seen':   d.last_seen,
                    'paired_at':   d.paired_at,
                    'total_readings': SensorReading.objects.filter(device=d).count(),
                }
                for d in devices
            ],
            'notifications': [
                {
                    'type':       n.type,
                    'title':      n.title,
                    'message':    n.message,
                    'device_name': n.device_name,
                    'is_read':    n.is_read,
                    'created_at': n.created_at,
                }
                for n in notifications
            ],
            'recent_weather': [
                {
                    'location':    l.location,
                    'success':     l.success,
                    'accessed_at': l.accessed_at,
                }
                for l in weather_logs
            ],
        })

    def delete(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            return Response({'detail': 'Cannot delete your own account.'}, status=status.HTTP_400_BAD_REQUEST)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        is_active = request.data.get('is_active')
        if is_active is not None:
            user.is_active = bool(is_active)
            user.save(update_fields=['is_active'])
        return Response({'id': user.id, 'is_active': user.is_active})


class AdminDeviceListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        devices = Device.objects.select_related('user').order_by('-created_at')
        data = [
            {
                'id':           d.id,
                'device_id':    d.device_id,
                'pairing_code': d.pairing_code,
                'secret_key':   d.secret_key[:6] + '…',
                'device_name':  d.device_name,
                'status':       d.status,
                'is_paired':    d.is_paired,
                'crop_type':    d.crop_type,
                'soil_type':    d.soil_type,
                'last_seen':    d.last_seen,
                'created_at':   d.created_at,
                'paired_at':    d.paired_at,
                'owner_id':     d.user.id,
                'owner_name':   d.user.full_name,
                'owner_email':  d.user.email or d.user.phone_number,
                'total_readings': SensorReading.objects.filter(device=d).count(),
            }
            for d in devices
        ]
        return Response(data)


class AdminDeviceDetailView(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request, pk):
        device = get_object_or_404(Device, pk=pk)
        device.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminGenerateDeviceView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        def gen_device_id():
            return 'EF-' + uuid.uuid4().hex[:8].upper()

        def gen_pairing_code():
            chars = string.ascii_uppercase + string.digits
            return ''.join(secrets.choice(chars) for _ in range(6))

        def gen_secret_key():
            return secrets.token_hex(32)

        # Ensure uniqueness
        device_id = gen_device_id()
        while Device.objects.filter(device_id=device_id).exists():
            device_id = gen_device_id()

        pairing_code = gen_pairing_code()
        while Device.objects.filter(pairing_code=pairing_code).exists():
            pairing_code = gen_pairing_code()

        secret_key = gen_secret_key()

        # Save the device record so users can pair it later
        Device.objects.create(
            user=request.user,
            device_id=device_id,
            pairing_code=pairing_code,
            secret_key=secret_key,
            device_name=f'Device {device_id}',
            is_paired=False,
            status='Offline',
        )

        return Response({
            'device_id':    device_id,
            'pairing_code': pairing_code,
            'secret_key':   secret_key,
        }, status=status.HTTP_200_OK)


class AdminDeviceStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        from django.utils import timezone
        from datetime import timedelta

        device  = get_object_or_404(Device, pk=pk)
        latest  = SensorReading.objects.filter(device=device).first()
        total   = SensorReading.objects.filter(device=device).count()
        now     = timezone.now()

        reading = None
        if latest:
            reading = {
                'soil_moisture': latest.soil_moisture,
                'temperature':   latest.temperature,
                'humidity':      latest.humidity,
                'water_tank':    latest.water_tank,
                'pump_status':   latest.pump_status,
                'irrig_cycles':  latest.irrig_cycles,
                'recorded_at':   latest.recorded_at,
            }

        # ── Diagnostics engine ───────────────────────────────────────────────
        issues = []

        def issue(severity, title, reason, fix):
            issues.append({'severity': severity, 'title': title, 'reason': reason, 'fix': fix})

        # 1. Not paired at all
        if not device.is_paired:
            issue('critical', 'Device Not Paired',
                  'This device has never been paired to any user account.',
                  'Share the Device ID and Pairing Code with the user so they can pair it from the Connect Device page.')

        # 2. Paired but never sent data
        elif total == 0:
            issue('critical', 'No Data Received',
                  'Device is paired but has never sent any sensor readings to the server.',
                  'Check that the device firmware has the correct Device ID and Secret Key, and that it can reach the API endpoint /api/sensor/ingest/.')

        # 3. Offline — was online before
        if device.is_paired and device.status == 'Offline' and device.last_seen:
            minutes_ago = (now - device.last_seen).total_seconds() / 60
            hours_ago   = minutes_ago / 60
            if hours_ago > 24:
                issue('critical', 'Device Offline — Long Duration',
                      f'Device has been offline for {int(hours_ago)} hours (last seen {device.last_seen.strftime("%Y-%m-%d %H:%M")}).',
                      'Check power supply, Wi-Fi connection, and that the device is physically running. Verify the device can reach the internet.')
            elif hours_ago > 1:
                issue('high', 'Device Offline',
                      f'Device went offline {int(hours_ago)} hour(s) ago.',
                      'Device may have lost power or Wi-Fi. Check the physical device and router.')
            else:
                issue('medium', 'Device Recently Offline',
                      f'Device went offline {int(minutes_ago)} minute(s) ago.',
                      'This may be a temporary dropout. Wait a few minutes and refresh.')

        # 4. Paired but status still Offline and never seen
        if device.is_paired and device.status == 'Offline' and not device.last_seen and total == 0:
            issue('critical', 'Never Connected After Pairing',
                  'Device was paired but has never come online or sent data.',
                  'Ensure the device firmware is flashed correctly with the right credentials and the device has internet access.')

        # 5. Stale data — online but readings are old
        if device.status == 'Online' and latest:
            age_minutes = (now - latest.recorded_at).total_seconds() / 60
            if age_minutes > 30:
                issue('high', 'Stale Sensor Data',
                      f'Device shows Online but last reading was {int(age_minutes)} minutes ago.',
                      'The device may be stuck in a loop or the sensor reporting interval is too long. Check firmware.')

        # 6. Sensor value anomalies
        if latest:
            if latest.soil_moisture is None:
                issue('high', 'Soil Moisture Sensor Missing',
                      'Soil moisture value is null in the latest reading.',
                      'Check the soil moisture sensor wiring and calibration on the device.')
            elif latest.soil_moisture < 0 or latest.soil_moisture > 100:
                issue('medium', 'Soil Moisture Out of Range',
                      f'Soil moisture reading is {latest.soil_moisture}% which is outside 0–100%.',
                      'Sensor may be damaged or miscalibrated. Check wiring and recalibrate.')

            if latest.temperature is None:
                issue('high', 'Temperature Sensor Missing',
                      'Temperature value is null in the latest reading.',
                      'Check the temperature/humidity sensor (e.g. DHT22) wiring.')
            elif latest.temperature < -10 or latest.temperature > 60:
                issue('medium', 'Temperature Out of Range',
                      f'Temperature reading is {latest.temperature}°C which seems abnormal.',
                      'Sensor may be faulty or exposed to extreme conditions.')

            if latest.humidity is None:
                issue('medium', 'Humidity Sensor Missing',
                      'Humidity value is null in the latest reading.',
                      'Check the humidity sensor wiring and connections.')

            if latest.water_tank is not None and latest.water_tank < 10:
                issue('high', 'Water Tank Critically Low',
                      f'Water tank level is at {latest.water_tank}%.',
                      'Refill the water tank immediately to avoid irrigation failure.')

        # 7. No crop/soil configured
        if device.is_paired:
            if not device.crop_type:
                issue('low', 'No Crop Type Set',
                      'Crop type has not been configured for this device.',
                      'User should set the crop type in Farm Settings for accurate irrigation planning.')
            if not device.soil_type:
                issue('low', 'No Soil Type Set',
                      'Soil type has not been configured for this device.',
                      'User should set the soil type in Farm Settings.')

        # 8. User account inactive
        if not device.user.is_active:
            issue('high', 'Owner Account Disabled',
                  f'The device owner ({device.user.full_name}) account is currently deactivated.',
                  'Reactivate the user account from the Admin Users panel.')

        return Response({
            'id':             device.id,
            'device_id':      device.device_id,
            'device_name':    device.device_name,
            'pairing_code':   device.pairing_code,
            'secret_key':     device.secret_key[:6] + '…',
            'status':         device.status,
            'is_paired':      device.is_paired,
            'crop_type':      device.crop_type,
            'soil_type':      device.soil_type,
            'last_seen':      device.last_seen,
            'created_at':     device.created_at,
            'paired_at':      device.paired_at,
            'owner_id':       device.user.id,
            'owner_name':     device.user.full_name,
            'owner_email':    device.user.email or device.user.phone_number,
            'owner_active':   device.user.is_active,
            'latest_reading': reading,
            'total_readings': total,
            'diagnostics':    issues,
        })


class AdminDeviceFixView(APIView):
    """Admin takes control: fix device config, force pair, reset, update crop/soil"""
    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        from django.utils import timezone
        device = get_object_or_404(Device, pk=pk)
        action = request.data.get('action')
        log = []

        if action == 'force_pair':
            # Assign device to a specific user and mark as paired
            user_id = request.data.get('user_id')
            if user_id:
                target = get_object_or_404(User, pk=user_id)
                device.user      = target
                device.is_paired = True
                device.paired_at = timezone.now()
                device.save(update_fields=['user', 'is_paired', 'paired_at'])
                log.append(f'Device force-paired to {target.full_name}.')
            else:
                return Response({'detail': 'user_id required for force_pair.'}, status=status.HTTP_400_BAD_REQUEST)

        elif action == 'unpair':
            # Reset pairing so user can re-pair
            device.is_paired = False
            device.paired_at = None
            device.status    = 'Offline'
            device.save(update_fields=['is_paired', 'paired_at', 'status'])
            log.append('Device unpaired. User can now re-pair with the same credentials.')

        elif action == 'reset_credentials':
            # Generate new pairing code and secret key
            chars = __import__('string').ascii_uppercase + __import__('string').digits
            new_pairing = ''.join(__import__('secrets').choice(chars) for _ in range(6))
            while Device.objects.filter(pairing_code=new_pairing).exclude(pk=pk).exists():
                new_pairing = ''.join(__import__('secrets').choice(chars) for _ in range(6))
            new_secret = __import__('secrets').token_hex(32)
            device.pairing_code = new_pairing
            device.secret_key   = new_secret
            device.is_paired    = False
            device.paired_at    = None
            device.save(update_fields=['pairing_code', 'secret_key', 'is_paired', 'paired_at'])
            log.append(f'Credentials reset. New pairing code: {new_pairing}')

        elif action == 'update_config':
            # Update device name, crop type, soil type
            fields = []
            for field in ['device_name', 'crop_type', 'soil_type']:
                val = request.data.get(field)
                if val is not None:
                    setattr(device, field, val)
                    fields.append(field)
            if fields:
                device.save(update_fields=fields)
                log.append(f'Updated: {", ".join(fields)}.')

        elif action == 'force_online':
            device.status    = 'Online'
            device.last_seen = timezone.now()
            device.save(update_fields=['status', 'last_seen'])
            log.append('Device status forced to Online.')

        elif action == 'force_offline':
            device.status = 'Offline'
            device.save(update_fields=['status'])
            log.append('Device status forced to Offline.')

        elif action == 'update_farm_settings':
            # Admin updates the user's farm settings on their behalf
            fs, _ = FarmSettings.objects.get_or_create(user=device.user)
            fields = []
            for field in ['soil_type', 'plant_type', 'moisture_min', 'moisture_max',
                          'moisture_critical_low', 'irrigation_duration', 'notes']:
                val = request.data.get(field)
                if val is not None:
                    setattr(fs, field, val)
                    fields.append(field)
            if fields:
                fs.save(update_fields=fields)
                log.append(f'Farm settings updated for {device.user.full_name}: {", ".join(fields)}.')

        elif action == 'set_weather_location':
            lat  = request.data.get('lat')
            lon  = request.data.get('lon')
            name = request.data.get('name', '').strip()
            if lat is None or lon is None:
                return Response({'detail': 'lat and lon are required.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError):
                return Response({'detail': 'lat and lon must be numbers.'}, status=status.HTTP_400_BAD_REQUEST)
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return Response({'detail': 'Coordinates out of range.'}, status=status.HTTP_400_BAD_REQUEST)
            fs, _ = FarmSettings.objects.get_or_create(user=device.user)
            fs.admin_weather_lat           = lat
            fs.admin_weather_lon           = lon
            fs.admin_weather_location_name = name
            fs.save(update_fields=['admin_weather_lat', 'admin_weather_lon', 'admin_weather_location_name'])
            log.append(f'Weather location set to {name or f"{lat},{lon}"} for {device.user.full_name}.')

            # Fetch live weather preview for the new location
            weather_preview = None
            try:
                from api.weather_cache import fetch_weather_with_cache
                cw, fc = fetch_weather_with_cache(lat, lon)
                if cw:
                    main    = cw.get('main', {})
                    weather = cw.get('weather', [{}])[0]
                    wind    = cw.get('wind', {})
                    condition_map = {
                        'clear sky': 'Sunny', 'few clouds': 'Partly Cloudy',
                        'scattered clouds': 'Partly Cloudy', 'broken clouds': 'Cloudy',
                        'overcast clouds': 'Cloudy', 'shower rain': 'Rainy',
                        'rain': 'Rainy', 'thunderstorm': 'Stormy', 'snow': 'Snowy',
                        'mist': 'Foggy', 'fog': 'Foggy', 'light rain': 'Rainy',
                        'moderate rain': 'Rainy', 'drizzle': 'Rainy',
                    }
                    desc = weather.get('description', '').lower()
                    temp = round(main.get('temp', 0))
                    rain_prob = 0
                    if fc and fc.get('list'):
                        first = fc['list'][0]
                        if 'rain' in first:
                            rain_prob = min(100, round(first['rain'].get('3h', 0) * 20))
                        elif desc in ('rainy', 'stormy'):
                            rain_prob = 70

                    # Simple pump estimation based on weather
                    base_duration = fs.irrigation_duration or 30
                    skip_irrigation = rain_prob >= 70
                    if not skip_irrigation:
                        heat_factor = 1.3 if temp > 30 else (0.8 if temp < 15 else 1.0)
                        rain_factor = max(0, 1 - rain_prob / 100)
                        duration = round(base_duration * heat_factor * rain_factor)
                        cycles   = 3 if temp > 30 else 2
                        water_l  = round(duration * cycles * 10 * 0.1, 1)
                    else:
                        duration = 0
                        cycles   = 0
                        water_l  = 0

                    weather_preview = {
                        'condition':    condition_map.get(desc, weather.get('description', '').title()),
                        'temperature':  temp,
                        'humidity':     main.get('humidity', 0),
                        'wind_speed':   round(wind.get('speed', 0) * 3.6),
                        'rain_prob':    rain_prob,
                        'location':     cw.get('name', name or f'{lat:.2f},{lon:.2f}'),
                        'pump': {
                            'skip':     skip_irrigation,
                            'cycles':   cycles,
                            'duration': duration,
                            'water_l':  water_l,
                            'reason':   'Rain expected — irrigation skipped' if skip_irrigation else f'{cycles} cycles × {duration} min',
                        },
                    }
            except Exception as e:
                weather_preview = {'error': str(e)}

            return Response({
                'success': True, 'log': log,
                'weather_lat': lat, 'weather_lon': lon, 'weather_location_name': name,
                'weather_preview': weather_preview,
            })
        else:
            return Response({'detail': f'Unknown action: {action}'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'success': True,
            'log':     log,
            'device_id':    device.device_id,
            'device_name':  device.device_name,
            'is_paired':    device.is_paired,
            'status':       device.status,
            'pairing_code': device.pairing_code,
            'crop_type':    device.crop_type,
            'soil_type':    device.soil_type,
        })


class AdminWeatherView(APIView):
    """Admin weather dashboard — status, usage logs, per-user access control"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from django.conf import settings as django_settings
        from api.models import WeatherAccessLog
        from django.utils import timezone
        from datetime import timedelta

        api_key = getattr(django_settings, 'OPENWEATHER_API_KEY', '')
        api_active = bool(api_key)

        # Test the API key live
        api_working = False
        api_error   = ''
        if api_active:
            try:
                import urllib.request, json
                url = f'https://api.openweathermap.org/data/2.5/weather?lat=0&lon=0&appid={api_key}'
                with urllib.request.urlopen(url, timeout=5) as r:
                    d = json.loads(r.read().decode())
                    api_working = 'weather' in d or 'main' in d
            except Exception as e:
                api_error = str(e)

        # Usage stats
        now   = timezone.now()
        logs  = WeatherAccessLog.objects.all()
        today = logs.filter(accessed_at__date=now.date()).count()
        week  = logs.filter(accessed_at__gte=now - timedelta(days=7)).count()
        total = logs.count()

        # Recent 20 logs
        recent = [
            {
                'user_name':  l.user.full_name,
                'user_email': l.user.email or l.user.phone_number,
                'avatar_url': l.user.avatar_url,
                'location':   l.location,
                'lat':        l.lat,
                'lon':        l.lon,
                'success':    l.success,
                'accessed_at': l.accessed_at,
            }
            for l in logs[:20]
        ]

        # Per-user access list with annotated counts (avoids N+1 queries)
        users = User.objects.filter(is_staff=False).annotate(
            usage_count=Count('weather_logs'),
            last_used=Max('weather_logs__accessed_at')
        ).order_by('full_name')
        
        user_access = [
            {
                'id':             u.id,
                'full_name':      u.full_name,
                'email':          u.email or u.phone_number,
                'avatar_url':     u.avatar_url,
                'weather_access': getattr(u, 'weather_access', True),
                'usage_count':    u.usage_count or 0,
                'last_used':      u.last_used,
            }
            for u in users
        ]

        return Response({
            'api_key_set':   api_active,
            'api_working':   api_working,
            'api_error':     api_error,
            'api_key_hint':  (api_key[:6] + '…' + api_key[-4:]) if len(api_key) > 10 else ('Not set' if not api_key else api_key),
            'stats': {
                'today': today,
                'week':  week,
                'total': total,
            },
            'recent_logs':  recent,
            'user_access':  user_access,
        })

    def patch(self, request):
        """Toggle weather access for a specific user"""
        user_id = request.data.get('user_id')
        access  = request.data.get('weather_access')
        if user_id is None or access is None:
            return Response({'detail': 'user_id and weather_access required.'}, status=status.HTTP_400_BAD_REQUEST)
        user = get_object_or_404(User, pk=user_id)
        user.weather_access = bool(access)
        user.save(update_fields=['weather_access'])
        return Response({'id': user.id, 'weather_access': user.weather_access})


class AdminSettingsView(APIView):
    """System on/off + maintenance message + create/manage sub-admins"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from api.models import SystemSettings
        from django.utils import timezone
        ss = SystemSettings.get()
        # Auto bring online if scheduled time has passed
        if not ss.system_online and ss.online_at and ss.online_at <= timezone.now():
            ss.system_online = True
            ss.online_at = None
            ss.save(update_fields=['system_online', 'online_at'])
        admins = User.objects.filter(is_staff=True).order_by('full_name')
        return Response({
            'system': {
                'online':               ss.system_online,
                'maintenance_title':    ss.maintenance_title,
                'maintenance_message':  ss.maintenance_message,
                'maintenance_sub':      ss.maintenance_sub,
                'online_at':            ss.online_at,
                'updated_at':           ss.updated_at,
                'updated_by':           ss.updated_by.full_name if ss.updated_by else None,
            },
            'admins': [
                {
                    'id':                 u.id,
                    'full_name':          u.full_name,
                    'email':              u.email or u.phone_number,
                    'admin_level':        u.admin_level,
                    'can_manage_users':   u.can_manage_users,
                    'can_manage_devices': u.can_manage_devices,
                    'can_manage_weather': u.can_manage_weather,
                    'can_manage_system':  u.can_manage_system,
                    'is_active':          u.is_active,
                    'created_at':         u.created_at,
                }
                for u in admins
            ],
        })

    def patch(self, request):
        from api.models import SystemSettings
        action = request.data.get('action')

        if action == 'toggle_system':
            from django.utils.dateparse import parse_datetime
            ss = SystemSettings.get()
            ss.system_online = request.data.get('online', not ss.system_online)
            if 'maintenance_title'   in request.data: ss.maintenance_title   = request.data['maintenance_title']
            if 'maintenance_message' in request.data: ss.maintenance_message = request.data['maintenance_message']
            if 'maintenance_sub'     in request.data: ss.maintenance_sub     = request.data['maintenance_sub']
            online_at_raw = request.data.get('online_at')
            ss.online_at = parse_datetime(online_at_raw) if online_at_raw else None
            ss.updated_by = request.user
            ss.save()
            return Response({
                'online':              ss.system_online,
                'maintenance_title':   ss.maintenance_title,
                'maintenance_message': ss.maintenance_message,
                'maintenance_sub':     ss.maintenance_sub,
                'online_at':           ss.online_at,
            })

        elif action == 'update_maintenance_text':
            ss = SystemSettings.get()
            if 'maintenance_title'   in request.data: ss.maintenance_title   = request.data['maintenance_title']
            if 'maintenance_message' in request.data: ss.maintenance_message = request.data['maintenance_message']
            if 'maintenance_sub'     in request.data: ss.maintenance_sub     = request.data['maintenance_sub']
            ss.updated_by = request.user
            ss.save()
            return Response({'saved': True})

        elif action == 'create_admin':
            email    = request.data.get('email', '').strip()
            phone    = request.data.get('phone_number', '').strip()
            name     = request.data.get('full_name', '').strip()
            level    = request.data.get('admin_level', 'moderator')
            perms    = request.data.get('permissions', {})

            if not name:
                return Response({'detail': 'full_name is required.'}, status=status.HTTP_400_BAD_REQUEST)
            if not email and not phone:
                return Response({'detail': 'Email or phone number is required.'}, status=status.HTTP_400_BAD_REQUEST)
            if email and User.objects.filter(email=email).exists():
                return Response({'detail': 'Email already in use.'}, status=status.HTTP_400_BAD_REQUEST)
            if phone and User.objects.filter(phone_number=phone).exists():
                return Response({'detail': 'Phone number already in use.'}, status=status.HTTP_400_BAD_REQUEST)

            otp = f'{secrets.randbelow(1_000_000):06d}'

            user = User.objects.create_user(
                password=otp,          # OTP is the temporary login password
                email=email or None,
                phone_number=phone or None,
                full_name=name,
                is_staff=True,
                admin_level=level,
                can_manage_users=perms.get('users', False),
                can_manage_devices=perms.get('devices', False),
                can_manage_weather=perms.get('weather', False),
                can_manage_system=perms.get('system', False),
                must_change_password=True,
                otp_code=otp,
            )
            return Response({
                'id': user.id, 'full_name': user.full_name,
                'email': user.email, 'phone_number': user.phone_number,
                'admin_level': user.admin_level,
                'otp': otp,
            }, status=status.HTTP_201_CREATED)

        elif action == 'update_admin':
            uid   = request.data.get('user_id')
            user  = get_object_or_404(User, pk=uid, is_staff=True)
            level = request.data.get('admin_level')
            perms = request.data.get('permissions', {})
            if level: user.admin_level = level
            if 'users'   in perms: user.can_manage_users   = perms['users']
            if 'devices' in perms: user.can_manage_devices = perms['devices']
            if 'weather' in perms: user.can_manage_weather = perms['weather']
            if 'system'  in perms: user.can_manage_system  = perms['system']
            user.save()
            return Response({'id': user.id, 'admin_level': user.admin_level})

        elif action == 'remove_admin':
            uid  = request.data.get('user_id')
            user = get_object_or_404(User, pk=uid)
            if user == request.user:
                return Response({'detail': 'Cannot demote yourself.'}, status=status.HTTP_400_BAD_REQUEST)
            user.is_staff = False
            user.admin_level = 'user'
            user.can_manage_users = user.can_manage_devices = False
            user.can_manage_weather = user.can_manage_system = False
            user.save()
            return Response({'id': user.id, 'demoted': True})

        return Response({'detail': f'Unknown action: {action}'}, status=status.HTTP_400_BAD_REQUEST)


class AdminPlantProfilesView(APIView):
    """CRUD for admin-managed plant profiles visible to users."""
    permission_classes = [IsAdminUser]

    DEFAULT_SEASON_ADJUST = {
        'long_rains': 0.4, 'cool_dry': 0.85,
        'short_rains': 0.5, 'hot_dry': 1.3, 'transition': 1.0,
    }

    def _serialize(self, p):
        return {
            'id': p.id, 'key': p.key, 'label': p.label,
            'water_demand_l_day': p.water_demand_l_day,
            'stress_temp_high': p.stress_temp_high,
            'stress_moisture_low': p.stress_moisture_low,
            'root_depth_factor': p.root_depth_factor,
            'season_adjust': {**self.DEFAULT_SEASON_ADJUST, **(p.season_adjust or {})},
            'is_active': p.is_active,
            'is_builtin': p.is_builtin,
            'updated_at': p.updated_at,
        }

    def get(self, request):
        profiles = PlantProfile.objects.all()
        return Response([self._serialize(p) for p in profiles])

    def post(self, request):
        key   = request.data.get('key', '').strip().lower().replace(' ', '_')
        label = request.data.get('label', '').strip()

        # ── Bulk seed: accept a list of plants ──────────────────────────────
        if isinstance(request.data, list):
            created, updated = 0, 0
            DEFAULT_SA = {
                'long_rains': 0.4, 'cool_dry': 0.85,
                'short_rains': 0.5, 'hot_dry': 1.3, 'transition': 1.0,
            }
            for item in request.data:
                k = item.get('key', '').strip().lower().replace(' ', '_')
                l = item.get('label', '').strip()
                if not k or not l:
                    continue
                p, was_created = PlantProfile.objects.get_or_create(
                    key=k,
                    defaults={
                        'label': l,
                        'water_demand_l_day': float(item.get('water_demand_l_day', 5.5)),
                        'stress_temp_high':   float(item.get('stress_temp_high', 32.0)),
                        'stress_moisture_low':float(item.get('stress_moisture_low', 30.0)),
                        'root_depth_factor':  float(item.get('root_depth_factor', 1.0)),
                        'season_adjust':      item.get('season_adjust', DEFAULT_SA),
                        'is_active':          bool(item.get('is_active', True)),
                        'is_builtin':         bool(item.get('is_builtin', True)),
                    }
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
            return Response({'created': created, 'updated': updated}, status=status.HTTP_200_OK)

        # ── Single plant ─────────────────────────────────────────────────────
        if not key or not label:
            return Response({'detail': 'key and label are required.'}, status=status.HTTP_400_BAD_REQUEST)
        # Use get_or_create so toggling a built-in twice doesn't 400
        p, created = PlantProfile.objects.get_or_create(
            key=key,
            defaults={
                'label': label,
                'water_demand_l_day': float(request.data.get('water_demand_l_day', 5.5)),
                'stress_temp_high':   float(request.data.get('stress_temp_high', 32.0)),
                'stress_moisture_low':float(request.data.get('stress_moisture_low', 30.0)),
                'root_depth_factor':  float(request.data.get('root_depth_factor', 1.0)),
                'season_adjust':      request.data.get('season_adjust', {}),
                'is_active':          bool(request.data.get('is_active', True)),
                'is_builtin':         bool(request.data.get('is_builtin', False)),
            }
        )
        if not created:
            # Already exists — update all provided fields
            fields = ['label', 'water_demand_l_day', 'stress_temp_high',
                      'stress_moisture_low', 'root_depth_factor', 'season_adjust', 'is_active']
            for f in fields:
                if f in request.data:
                    val = request.data[f]
                    if f in ('water_demand_l_day', 'stress_temp_high', 'stress_moisture_low', 'root_depth_factor'):
                        val = float(val)
                    setattr(p, f, val)
            p.save()
        return Response(self._serialize(p), status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)

    def patch(self, request, pk=None):
        p = get_object_or_404(PlantProfile, pk=pk)
        fields = ['label', 'water_demand_l_day', 'stress_temp_high',
                  'stress_moisture_low', 'root_depth_factor', 'season_adjust', 'is_active']
        for f in fields:
            if f in request.data:
                val = request.data[f]
                if f in ('water_demand_l_day', 'stress_temp_high', 'stress_moisture_low', 'root_depth_factor'):
                    val = float(val)
                setattr(p, f, val)
        p.save()
        return Response(self._serialize(p))

    def delete(self, request, pk=None):
        p = get_object_or_404(PlantProfile, pk=pk)
        if p.is_builtin:
            return Response({'detail': 'Built-in profiles cannot be deleted — disable them instead.'}, status=status.HTTP_400_BAD_REQUEST)
        p.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SystemStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from api.models import SystemSettings
        from django.utils import timezone
        ss = SystemSettings.get()
        # Auto bring online if scheduled time has passed
        if not ss.system_online and ss.online_at and ss.online_at <= timezone.now():
            ss.system_online = True
            ss.online_at = None
            ss.save(update_fields=['system_online', 'online_at'])
        return Response({
            'online':              ss.system_online,
            'maintenance_title':   ss.maintenance_title,
            'maintenance_message': ss.maintenance_message,
            'maintenance_sub':     ss.maintenance_sub,
            'online_at':           ss.online_at,
        })
