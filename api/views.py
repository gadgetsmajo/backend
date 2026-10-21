from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.conf import settings
from .models import Device, Notification, FarmSettings, SensorReading, DailyAgriLog, LocationCache, PumpCommand, PlantProfile, SMSSettings, HardwareOrder, InvestorApplication, BusinessRequest, PartnershipApplication
from .intelligence import detect_season, get_crop_profile, compute_drying_rate, compute_smart_irrigation
from .serializers import (
    DeviceSerializer, ConnectDeviceSerializer, NotificationSerializer,
    FarmSettingsSerializer, PairDeviceSerializer, TestDeviceSerializer,
    SensorReadingSerializer, SensorIngestSerializer, SMSSettingsSerializer,
)
from . import notification_service as ns


class HardwareOrderListView(APIView):
    """GET /api/orders/hardware/ — admin only, returns all orders newest first."""

    def get(self, request):
        orders = HardwareOrder.objects.all()
        data = [{
            'id':         o.id,
            'name':       o.name,
            'phone':      o.phone,
            'email':      o.email,
            'location':   o.location,
            'kit_type':   o.kit_type,
            'quantity':   o.quantity,
            'total_ugx':  o.total_ugx,
            'notes':      o.notes,
            'status':     o.status,
            'created_at': o.created_at.isoformat(),
        } for o in orders]
        return Response(data)


class HardwareOrderDetailView(APIView):
    """PATCH /api/orders/hardware/<id>/ — admin only, update status."""

    def patch(self, request, pk):
        order = get_object_or_404(HardwareOrder, pk=pk)
        new_status = request.data.get('status')
        valid = [s[0] for s in HardwareOrder.STATUS_CHOICES]
        if new_status not in valid:
            return Response({'detail': f'Invalid status. Choose from {valid}.'}, status=status.HTTP_400_BAD_REQUEST)
        order.status = new_status
        order.save(update_fields=['status'])
        return Response({'id': order.id, 'status': order.status})


class HardwareOrderView(APIView):
    """
    POST /api/orders/hardware/
    Anyone can place an order (no auth required).
    Creates a HardwareOrder, notifies all admin accounts via Notification,
    and sends a WhatsApp message to 0786023858.
    """
    permission_classes = [AllowAny]

    PRICES = {'basic': 700_000, 'advanced': 2_000_000}
    WHATSAPP_NUMBER = '256786023858'  # 0786023858 in international format

    def post(self, request):
        data     = request.data
        name     = data.get('name', '').strip()
        phone    = data.get('phone', '').strip()
        email    = data.get('email', '').strip()
        location = data.get('location', '').strip()
        kit_type = data.get('kit_type', '').strip()
        quantity = int(data.get('quantity', 1))
        notes    = data.get('notes', '').strip()

        if not name or not phone:
            return Response({'detail': 'Name and phone are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if kit_type not in self.PRICES:
            return Response({'detail': 'Invalid kit type.'}, status=status.HTTP_400_BAD_REQUEST)
        if quantity < 1 or quantity > 10:
            return Response({'detail': 'Quantity must be between 1 and 10.'}, status=status.HTTP_400_BAD_REQUEST)

        total = self.PRICES[kit_type] * quantity
        order = HardwareOrder.objects.create(
            name=name, phone=phone, email=email, location=location,
            kit_type=kit_type, quantity=quantity, total_ugx=total, notes=notes,
        )

        kit_label = dict(HardwareOrder.KIT_CHOICES)[kit_type]
        msg = (
            f'New hardware order #{order.id}\n'
            f'Kit: {kit_label} x{quantity}\n'
            f'Total: UGX {total:,}\n'
            f'Customer: {name} | {phone}'
            + (f' | {email}' if email else '')
            + (f'\nLocation: {location}' if location else '')
            + (f'\nNotes: {notes}' if notes else '')
        )

        # Notify all admin users in-app
        from users.models import User
        admins = User.objects.filter(is_staff=True)
        for admin in admins:
            Notification.objects.create(
                user=admin, type='system',
                title=f'New Hardware Order #{order.id}',
                message=msg,
            )

        # Build WhatsApp deep-link (backend returns it; frontend opens it)
        import urllib.parse
        wa_text = urllib.parse.quote(msg)
        whatsapp_url = f'https://wa.me/{self.WHATSAPP_NUMBER}?text={wa_text}'

        return Response({
            'order_id':      order.id,
            'status':        order.status,
            'total_ugx':     total,
            'whatsapp_url':  whatsapp_url,
        }, status=status.HTTP_201_CREATED)


class InvestorApplicationView(APIView):
    """POST /api/investor-applications/ — submit an investor application."""
    permission_classes = [AllowAny]

    REQUIRED_FIELDS = ('name', 'email', 'location', 'village_parish', 'country', 'amount', 'currency', 'source', 'timeline')

    def post(self, request):
        data = request.data
        values = {field: str(data.get(field, '')).strip() for field in self.REQUIRED_FIELDS}
        missing = [field for field, value in values.items() if not value]
        if missing:
            return Response({'detail': f'Missing required fields: {", ".join(missing)}.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount = float(values['amount'])
        except ValueError:
            return Response({'detail': 'Investment amount must be a number.'}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= 0:
            return Response({'detail': 'Investment amount must be greater than zero.'}, status=status.HTTP_400_BAD_REQUEST)

        optional = {field: str(data.get(field, '')).strip() for field in ('organisation', 'phone', 'experience', 'message')}

        InvestorApplication.objects.create(
            name=values['name'], organisation=optional['organisation'],
            email=values['email'], phone=optional['phone'],
            location=values['location'], village_parish=values['village_parish'],
            country=values['country'], amount=amount, currency=values['currency'],
            source=values['source'], timeline=values['timeline'],
            experience=optional['experience'], message=optional['message'],
        )

        message = (
            'New investor application\n'
            f'Name: {values["name"]}\nOrganisation: {optional["organisation"] or "Not provided"}\n'
            f'Email: {values["email"]}\nPhone: {optional["phone"] or "Not provided"}\n'
            f'Location: {values["location"]}, {values["village_parish"]}, {values["country"]}\n'
            f'Planned investment: {values["currency"]} {amount:,.2f}\nSource: {values["source"]}\nTimeline: {values["timeline"]}'
        )
        from users.models import User
        for admin in User.objects.filter(is_staff=True):
            Notification.objects.create(user=admin, type='system', title=f'New Investor Application: {values["name"]}', message=message)

        return Response({'detail': 'Investor application submitted.'}, status=status.HTTP_201_CREATED)


class InvestorApplicationListView(APIView):
    """GET /api/investor-applications/list/ — admin only."""
    def get(self, request):
        apps = InvestorApplication.objects.all()
        return Response([{
            'id': a.id, 'name': a.name, 'organisation': a.organisation,
            'email': a.email, 'phone': a.phone, 'location': a.location,
            'village_parish': a.village_parish, 'country': a.country,
            'amount': a.amount, 'currency': a.currency, 'source': a.source,
            'timeline': a.timeline, 'experience': a.experience, 'message': a.message,
            'created_at': a.created_at.isoformat(),
        } for a in apps])


class BusinessRequestView(APIView):
    """POST /api/business-requests/ — submit a partner or information request."""
    permission_classes = [AllowAny]

    REQUIRED_FIELDS = ('name', 'email', 'location', 'village_parish', 'country', 'request_type', 'message')
    ALLOWED_REQUEST_TYPES = ('Strategic Partnership', 'Distribution Opportunity', 'Other')

    def post(self, request):
        data = request.data
        values = {field: str(data.get(field, '')).strip() for field in self.REQUIRED_FIELDS}
        missing = [field for field, value in values.items() if not value]
        if missing:
            return Response({'detail': f'Missing required fields: {", ".join(missing)}.'}, status=status.HTTP_400_BAD_REQUEST)
        if values['request_type'] not in self.ALLOWED_REQUEST_TYPES:
            return Response({'detail': 'Invalid request type.'}, status=status.HTTP_400_BAD_REQUEST)

        optional = {f: str(data.get(f, '')).strip() for f in ('organisation', 'phone')}

        BusinessRequest.objects.create(
            name=values['name'], organisation=optional['organisation'],
            email=values['email'], phone=optional['phone'],
            location=values['location'], village_parish=values['village_parish'],
            country=values['country'], request_type=values['request_type'],
            message=values['message'],
        )

        message = (
            'New business request\n'
            f'Name: {values["name"]}\nOrganisation: {optional["organisation"] or "Not provided"}\n'
            f'Email: {values["email"]}\nPhone: {optional["phone"] or "Not provided"}\n'
            f'Location: {values["location"]}, {values["village_parish"]}, {values["country"]}\n'
            f'Request type: {values["request_type"]}\nMessage: {values["message"]}'
        )
        from users.models import User
        for admin in User.objects.filter(is_staff=True):
            Notification.objects.create(user=admin, type='system', title=f'New Business Request: {values["request_type"]}', message=message)

        return Response({'detail': 'Request submitted.'}, status=status.HTTP_201_CREATED)


class BusinessRequestListView(APIView):
    """GET /api/business-requests/list/ — admin only."""
    def get(self, request):
        reqs = BusinessRequest.objects.all()
        return Response([{
            'id': r.id, 'name': r.name, 'organisation': r.organisation,
            'email': r.email, 'phone': r.phone, 'location': r.location,
            'village_parish': r.village_parish, 'country': r.country,
            'request_type': r.request_type, 'message': r.message,
            'created_at': r.created_at.isoformat(),
        } for r in reqs])


class PartnershipApplicationView(APIView):
    """POST /api/partnership-applications/ — submit a partnership application."""
    permission_classes = [AllowAny]

    REQUIRED_FIELDS = ('name', 'email', 'location', 'village_parish', 'country', 'partner_type', 'interest', 'message')

    def post(self, request):
        data = request.data
        values = {field: str(data.get(field, '')).strip() for field in self.REQUIRED_FIELDS}
        missing = [field for field, value in values.items() if not value]
        if missing:
            return Response({'detail': f'Missing required fields: {", ".join(missing)}.'}, status=status.HTTP_400_BAD_REQUEST)

        optional = {f: str(data.get(f, '')).strip() for f in ('organisation', 'phone', 'website', 'business_area', 'products', 'markets', 'capacity')}

        PartnershipApplication.objects.create(
            name=values['name'], organisation=optional['organisation'],
            email=values['email'], phone=optional['phone'],
            location=values['location'], village_parish=values['village_parish'],
            country=values['country'], partner_type=values['partner_type'],
            business_area=optional['business_area'], products=optional['products'],
            markets=optional['markets'], capacity=optional['capacity'],
            website=optional['website'], interest=values['interest'],
            message=values['message'],
        )

        message = (
            'New partnership application\n'
            f'Contact: {values["name"]}\nOrganisation: {optional["organisation"] or "Not provided"}\n'
            f'Email: {values["email"]}\nPhone: {optional["phone"] or "Not provided"}\n'
            f'Location: {values["location"]}, {values["village_parish"]}, {values["country"]}\n'
            f'Partner type: {values["partner_type"]}\nInterest: {values["interest"]}'
        )
        from users.models import User
        for admin in User.objects.filter(is_staff=True):
            Notification.objects.create(user=admin, type='system', title=f'New Partnership Application: {values["partner_type"]}', message=message)

        return Response({'detail': 'Partnership application submitted.'}, status=status.HTTP_201_CREATED)


class PartnershipApplicationListView(APIView):
    """GET /api/partnership-applications/list/ — admin only."""
    def get(self, request):
        apps = PartnershipApplication.objects.all()
        return Response([{
            'id': a.id, 'name': a.name, 'organisation': a.organisation,
            'email': a.email, 'phone': a.phone, 'location': a.location,
            'village_parish': a.village_parish, 'country': a.country,
            'partner_type': a.partner_type, 'business_area': a.business_area,
            'products': a.products, 'markets': a.markets, 'capacity': a.capacity,
            'website': a.website, 'interest': a.interest, 'message': a.message,
            'created_at': a.created_at.isoformat(),
        } for a in apps])

class HealthCheckView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'status': 'ok'})

    def head(self, request):
        return Response()


class DashboardView(APIView):
    def get(self, request):
        from datetime import datetime, timedelta
        from django.conf import settings as django_settings
        from .weather_cache import fetch_weather_with_cache

        if request.user.is_staff:
            devices = Device.objects.all()
        else:
            devices = Device.objects.filter(user=request.user)
        online  = devices.filter(status='Online').first()

        location = getattr(django_settings, 'DEFAULT_WEATHER_LOCATION', {'lat': 40.7128, 'lon': -74.0060})
        fs = FarmSettings.objects.filter(user=request.user).first()
        if fs and fs.admin_weather_lat is not None:
            location = {'lat': fs.admin_weather_lat, 'lon': fs.admin_weather_lon}
        elif fs and fs.weather_lat is not None:
            location = {'lat': fs.weather_lat, 'lon': fs.weather_lon}
        lat = float(request.GET.get('lat', location['lat']))
        lon = float(request.GET.get('lon', location['lon']))

        temperature, humidity, wind_speed, weather_condition, rain_probability = 0, 0, 0, '—', 0
        temperature_trend = []

        try:
            cw, fc = fetch_weather_with_cache(lat, lon)

            if cw and fc:
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
                temperature       = round(main.get('temp', 0))
                humidity          = main.get('humidity', 0)
                wind_speed        = round(wind.get('speed', 0) * 3.6)
                weather_condition = condition_map.get(desc, weather.get('description', '—').title())

                # Build temperature trend from next 8 forecast slots (3-hour intervals)
                for item in fc.get('list', [])[:8]:
                    dt = datetime.fromtimestamp(item['dt'])
                    temperature_trend.append({
                        'time':        dt.strftime('%H:%M'),
                        'temperature': round(item['main']['temp']),
                        'humidity':    item['main']['humidity'],
                    })

                # Rain probability from first forecast slot
                if fc.get('list'):
                    first = fc['list'][0]
                    if 'rain' in first:
                        rain_probability = min(100, round(first['rain'].get('3h', 0) * 20))
                    elif weather_condition in ('Rainy', 'Stormy'):
                        rain_probability = 70

        except Exception as e:
            print(f"Dashboard weather fetch error: {e}")

        # Fetch latest sensor reading from the first online device
        soil_moisture, water_tank_level, pump_status, irrigation_cycles = 0, 0, 'Off', 0
        moisture_trend = []
        soil_temperature_trend = []
        soil_humidity_trend = []
        irrigation_history = []

        if online:
            latest_reading = SensorReading.objects.filter(device=online).order_by('-recorded_at').first()
            if latest_reading:
                soil_moisture = latest_reading.soil_moisture or 0
                water_tank_level = latest_reading.water_tank or 0
                pump_status = latest_reading.pump_status
                irrigation_cycles = latest_reading.irrig_cycles or 0

            # Build moisture trend from last 24 readings
            from django.utils import timezone
            twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
            recent_readings = SensorReading.objects.filter(
                device=online,
                recorded_at__gte=twenty_four_hours_ago
            ).order_by('recorded_at')[:24]

            moisture_trend = [
                {'time': r.recorded_at.strftime('%H:%M'), 'moisture': r.soil_moisture or 0}
                for r in recent_readings
            ]
            soil_temperature_trend = [
                {'time': r.recorded_at.strftime('%H:%M'), 'temperature': r.temperature or 0}
                for r in recent_readings if r.temperature is not None
            ]
            soil_humidity_trend = [
                {'time': r.recorded_at.strftime('%H:%M'), 'humidity': r.humidity or 0}
                for r in recent_readings if r.humidity is not None
            ]
            irrigation_history = [
                {'time': r.recorded_at.strftime('%H:%M'), 'cycles': r.irrig_cycles or 0}
                for r in recent_readings
            ]

        data = {
            'device_status':      online.status if online else 'Offline',
            'soil_moisture':      soil_moisture,
            'temperature':        temperature,
            'humidity':           humidity,
            'wind_speed':         wind_speed,
            'rain_probability':   rain_probability,
            'weather_condition':  weather_condition,
            'water_tank_level':   water_tank_level,
            'pump_status':        pump_status,
            'irrigation_cycles':  irrigation_cycles,
            'moisture_trend':          moisture_trend,
            'temperature_trend':        temperature_trend,
            'soil_temperature_trend':   soil_temperature_trend,
            'soil_humidity_trend':      soil_humidity_trend,
            'irrigation_history':       irrigation_history,
        }
        return Response(data)


class DeviceListView(APIView):
    def get(self, request):
        devices = Device.objects.filter(user=request.user).order_by('-created_at')
        return Response(DeviceSerializer(devices, many=True).data)


class DeviceDetailView(APIView):
    def _get_device(self, request, pk):
        return get_object_or_404(Device, pk=pk, user=request.user)

    def put(self, request, pk):
        device = self._get_device(request, pk)
        serializer = DeviceSerializer(device, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        self._get_device(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConnectDeviceView(APIView):
    def post(self, request):
        serializer = ConnectDeviceSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            device = serializer.save()
            return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PairDeviceView(APIView):
    """Pair a hardware device using Device ID and Pairing Code"""
    def post(self, request):
        serializer = PairDeviceSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            device = serializer.save()
            return Response({
                'success': True,
                'message': 'Device successfully paired to your account.',
                'device': DeviceSerializer(device).data
            }, status=status.HTTP_200_OK)
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class TestDeviceView(APIView):
    """Test hardware device connection — queries real sensor data if available"""
    def post(self, request):
        serializer = TestDeviceSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            device = serializer.validated_data['device']
            
            # Try to fetch real sensor data from device
            latest_reading = SensorReading.objects.filter(device=device).first()
            
            if latest_reading:
                # Real device data exists — use it
                test_results = {
                    'success': True,
                    'device_id': device.device_id,
                    'device_name': device.device_name,
                    'checks': {
                        'device_found': True,
                        'online_status': 'Online',
                        'temperature_reading': latest_reading.temperature,
                        'soil_moisture': latest_reading.soil_moisture,
                        'pump_status': latest_reading.pump_status,
                        'reading_source': 'real',
                        'last_update': latest_reading.recorded_at.isoformat(),
                    },
                    'message': 'Device test successful! Latest sensor data received.'
                }
            else:
                # No sensor data yet — use simulated values with clear labeling
                test_results = {
                    'success': True,
                    'device_id': device.device_id,
                    'device_name': device.device_name,
                    'checks': {
                        'device_found': True,
                        'online_status': 'Online',
                        'temperature_reading': None,
                        'soil_moisture': None,
                        'pump_status': 'Off',
                        'reading_source': 'simulated',
                        'note': 'Device test passed but no sensor data received yet. Wait for device to send readings.',
                    },
                    'message': 'Device found and online, but waiting for first sensor reading. Keep the device powered on.'
                }
            
            return Response(test_results, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class NotificationUnreadCountView(APIView):
    def get(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'count': count})


class NotificationListView(APIView):
    def get(self, request):
        notifications = Notification.objects.filter(user=request.user)
        return Response(NotificationSerializer(notifications, many=True).data)

    def post(self, request):
        # Gracefully handle stray POSTs caused by axios interceptor method loss on token refresh
        return Response(
            NotificationSerializer(
                Notification.objects.filter(user=request.user), many=True
            ).data
        )


class NotificationDetailView(APIView):
    def patch(self, request, pk):
        n = get_object_or_404(Notification, pk=pk, user=request.user)
        serializer = NotificationSerializer(n, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NotificationMarkAllReadView(APIView):
    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        # Tell the frontend to clear the app badge
        return Response({'status': 'ok', 'badge_count': 0})


class FarmSettingsView(APIView):
    def get(self, request):
        obj, _ = FarmSettings.objects.get_or_create(user=request.user)
        return Response(FarmSettingsSerializer(obj).data)

    def post(self, request):
        obj, _ = FarmSettings.objects.get_or_create(user=request.user)
        serializer = FarmSettingsSerializer(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SensorIngestView(APIView):
    """Hardware POSTs readings here — no user auth, uses device secret_key"""
    permission_classes = [AllowAny]

    def post(self, request):
        from django.utils import timezone
        serializer = SensorIngestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        d = serializer.validated_data
        device = d['device']
        reading = SensorReading.objects.create(
            device=device,
            soil_moisture=d.get('soil_moisture'),
            temperature=d.get('temperature'),
            humidity=d.get('humidity'),
            water_tank=d.get('water_tank'),
            pump_status=d.get('pump_status', 'Off'),
            irrig_cycles=d.get('irrig_cycles', 0),
            gps_lat=d.get('gps_lat'),
            gps_lon=d.get('gps_lon'),
            gps_place=d.get('gps_place', ''),
        )
        # Also update device GPS location in FarmSettings if we got a fix
        if d.get('gps_lat') and d.get('gps_lon'):
            try:
                fs, _ = FarmSettings.objects.get_or_create(user=device.user)
                if fs.weather_lat is None:  # only set if user hasn't manually set one
                    fs.weather_lat = d['gps_lat']
                    fs.weather_lon = d['gps_lon']
                    if d.get('gps_place'):
                        fs.weather_location_name = d['gps_place']
                    fs.save(update_fields=['weather_lat', 'weather_lon', 'weather_location_name'])
            except Exception:
                pass
        device.status    = 'Online'
        device.last_seen = timezone.now()
        device.save(update_fields=['status', 'last_seen'])
        # Auto-create notifications for critical thresholds
        ns.check_sensor_thresholds(device, reading)
        return Response({'status': 'ok', 'id': reading.id}, status=status.HTTP_201_CREATED)


class PumpCommandPollView(APIView):
    """
    Hardware polls this to get the latest pending pump command.
    Auth: device_id + secret_key.
    GET /api/pump/poll/?device_id=X&secret_key=Y
    Returns the latest unacknowledged command, then marks it acknowledged.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        device_id  = request.GET.get('device_id', '').strip()
        secret_key = request.GET.get('secret_key', '').strip()
        if not device_id or not secret_key:
            return Response({'error': 'device_id and secret_key required'}, status=status.HTTP_400_BAD_REQUEST)
        device = Device.objects.filter(device_id=device_id, secret_key=secret_key).first()
        if not device:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

        # Get latest command not yet acknowledged by hardware
        cmd = PumpCommand.objects.filter(device=device, acknowledged=False).order_by('-issued_at').first()
        if not cmd:
            return Response({'pending': False})

        # Mark acknowledged
        PumpCommand.objects.filter(pk=cmd.pk).update(acknowledged=True)
        return Response({'pending': True, 'command': cmd.command})


class LiveDataView(APIView):
    """Returns latest reading + history for the user's devices"""

    def get(self, request):
        device_id = request.GET.get('device_id')
        # Admins see all devices; regular users see only their own
        if request.user.is_staff:
            devices = Device.objects.all()
        else:
            devices = Device.objects.filter(user=request.user)
        if device_id:
            devices = devices.filter(device_id=device_id)

        # Latest reading per device
        latest = []
        for dev in devices:
            r = SensorReading.objects.filter(device=dev).order_by('-recorded_at').first()
            if r:
                latest.append(SensorReadingSerializer(r).data)

        # History: last 50 readings ordered oldest -> newest for charts
        qs = SensorReading.objects.filter(device__in=devices).order_by('-recorded_at')[:50]
        history = SensorReadingSerializer(list(reversed(list(qs))), many=True).data

        # Device list for selector
        device_list = DeviceSerializer(devices, many=True).data

        return Response({
            'devices':  device_list,
            'latest':   latest,
            'history':  history,
        })


class PumpControlView(APIView):
    """Queue manual pump commands or return the device to automatic irrigation."""

    def post(self, request):
        device_id  = request.data.get('device_id')
        mode       = request.data.get('mode', 'manual')
        pump_on    = request.data.get('pump_on', False)
        if request.user.is_staff:
            device = get_object_or_404(Device, device_id=device_id)
        else:
            device = get_object_or_404(Device, device_id=device_id, user=request.user)
        
        # Record pump command separately (not in sensor readings)
        if mode == 'wake':
            command_status = 'Wake'
        else:
            command_status = 'Auto' if mode == 'auto' else ('On' if pump_on else 'Off')
        PumpCommand.objects.create(
            device=device,
            command=command_status,
            issued_by=request.user,
        )
        
        return Response({'status': 'ok', 'pump_status': command_status})


class WifiStatusView(APIView):
    def get(self, request):
        return Response({
            'ssid':    None,
            'status':  'Disconnected',
            'rssi':    None,
            'signal':  None,
            'ip':      None,
            'mac':     None,
            'bssid':   None,
            'channel': None,
        })


class WifiScanView(APIView):
    def get(self, request):
        return Response({'networks': []})


class WifiConfigureView(APIView):
    def post(self, request):
        ssid     = request.data.get('ssid', '').strip()
        password = request.data.get('password', '').strip()
        if not ssid:
            return Response({'detail': 'SSID is required.'}, status=status.HTTP_400_BAD_REQUEST)
        # Save to the user's first device so hardware can poll and apply
        device = Device.objects.filter(user=request.user).first()
        if device:
            device.wifi_ssid     = ssid
            device.wifi_password = password
            device.wifi_pending  = True
            device.save(update_fields=['wifi_ssid', 'wifi_password', 'wifi_pending'])
        return Response({
            'message':    f'Configuration for "{ssid}" saved. Device will apply on next poll.',
            'connection': {'ssid': ssid, 'status': 'Pending'},
        })


class WifiCredentialsFetchView(APIView):
    """
    Hardware polls this to get pending WiFi credentials.
    Auth: device_id + secret_key.
    GET /api/wifi/credentials/?device_id=X&secret_key=Y
    Returns ssid+password only when wifi_pending=True, then clears the flag.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        device_id  = request.GET.get('device_id', '').strip()
        secret_key = request.GET.get('secret_key', '').strip()
        if not device_id or not secret_key:
            return Response({'error': 'device_id and secret_key are required'}, status=status.HTTP_400_BAD_REQUEST)
        device = Device.objects.filter(device_id=device_id, secret_key=secret_key).first()
        if not device:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        if not device.wifi_pending:
            return Response({'pending': False})
        ssid     = device.wifi_ssid
        password = device.wifi_password
        Device.objects.filter(pk=device.pk).update(wifi_pending=False)
        return Response({'pending': True, 'ssid': ssid, 'password': password})


class WeatherLocationSettingsView(APIView):
    """Get or set weather location for the user"""
    def get(self, request):
        from django.conf import settings as django_settings
        
        # Get user's saved location or default
        settings_obj, _ = FarmSettings.objects.get_or_create(user=request.user)
        
        if hasattr(settings_obj, 'weather_lat') and settings_obj.weather_lat:
            location = {
                'lat': settings_obj.weather_lat,
                'lon': settings_obj.weather_lon,
                'name': getattr(settings_obj, 'weather_location_name', 'Custom Location')
            }
        else:
            location = getattr(django_settings, 'DEFAULT_WEATHER_LOCATION', {
                'lat': 40.7128, 'lon': -74.0060, 'name': 'New York City'
            })
        
        return Response(location)
    
    def post(self, request):
        """Update user's weather location"""
        lat = request.data.get('lat')
        lon = request.data.get('lon')
        name = request.data.get('name', 'Custom Location')
        
        if not lat or not lon:
            return Response(
                {'error': 'Latitude and longitude are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            lat = float(lat)
            lon = float(lon)
            
            # Validate coordinates
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return Response(
                    {'error': 'Invalid coordinates'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Save to user settings (we'll need to add these fields to FarmSettings model)
            settings_obj, _ = FarmSettings.objects.get_or_create(user=request.user)
            
            # For now, we'll store in a simple way - you may want to add proper model fields
            # This is a minimal implementation
            return Response({
                'message': 'Location updated successfully',
                'location': {'lat': lat, 'lon': lon, 'name': name}
            })
            
        except ValueError:
            return Response(
                {'error': 'Invalid coordinate format'}, 
                status=status.HTTP_400_BAD_REQUEST
            )




class WeatherView(APIView):
    def get(self, request):
        # Check if user has weather access
        if not getattr(request.user, 'weather_access', True):
            return Response(
                {'detail': 'Weather access has been disabled for your account.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            # Check if OpenWeather API is configured
            api_key = getattr(settings, 'OPENWEATHER_API_KEY', '').strip()
            if not api_key:
                print('[WeatherView] WARNING: OPENWEATHER_API_KEY not configured. Returning fallback data.')
                # Return fallback data if API key is not configured
                from datetime import datetime
                return Response({
                    'current': {
                        'condition': 'sunny', 'temperature': 24, 'humidity': 60,
                        'rain_probability': 10, 'wind_speed': 14, 'pressure': 1013,
                        'visibility': 10, 'feels_like': 26,
                        'description': 'Weather service not configured',
                        'location': 'Default Location',
                        'updated_at': datetime.utcnow().isoformat() + 'Z',
                        'irrigation': {
                            'water_total_l': 10,
                            'pump_duration_min': 30,
                            'rain_saving_l': 0,
                            'reason': 'API key not configured',
                            'pump_times': [],
                        },
                    },
                    'forecast': [
                        {
                            'day': 'Mon', 'date': datetime.now().strftime('%Y-%m-%d'),
                            'condition': 'sunny', 'temp_high': 25, 'temp_low': 15,
                            'rain_probability': 10, 'irrigation': {
                                'water_total_l': 10, 'pump_duration_min': 30,
                                'rain_saving_l': 0, 'reason': 'API key not configured',
                                'pump_times': [],
                            },
                        }
                    ],
                    'hourly': [],
                    'intelligence': {
                        'season': {'key': 'spring', 'label': 'Spring'},
                        'crop': {
                            'key': 'general', 'label': 'General',
                            'stress_temp': 35, 'stress_moisture': 20,
                            'season_factor': 1.0,
                        },
                        'drying': {'drying_mm_day': 0},
                        'log_count': 0,
                    },
                    'irrigation_settings': {
                        'base_duration_min': 30,
                        'soil_type': 'Loam',
                        'plant_type': 'General',
                        'pump_flow_rate': 10,
                        'weekly_water_l': 70,
                        'weekly_saving_l': 0,
                    },
                })
            
            # Get location from settings or request parameters
            location = getattr(settings, 'DEFAULT_WEATHER_LOCATION', {
                'lat': 40.7128, 'lon': -74.0060, 'name': 'New York City'
            })
            fs_loc = FarmSettings.objects.filter(user=request.user).first()
            if fs_loc and fs_loc.admin_weather_lat is not None:
                location = {'lat': fs_loc.admin_weather_lat, 'lon': fs_loc.admin_weather_lon}
            elif fs_loc and fs_loc.weather_lat is not None:
                location = {'lat': fs_loc.weather_lat, 'lon': fs_loc.weather_lon}
            
            # Allow override via query parameters
            lat = float(request.GET.get('lat', location['lat']))
            lon = float(request.GET.get('lon', location['lon']))

            # Fetch weather data (served from cache when available)
            from .weather_cache import fetch_weather_with_cache
            current_data, forecast_data = fetch_weather_with_cache(lat, lon)
            current_weather = self._parse_current_weather(current_data)
            forecast_list = self._parse_forecast(forecast_data)
            
            # Get farm settings for irrigation calculations
            settings_obj, _ = FarmSettings.objects.get_or_create(user=request.user)
            base_duration = settings_obj.irrigation_duration
            soil_type = settings_obj.soil_type or 'Loam'
            plant_type = (settings_obj.plant_type or 'General').strip().lower()

            # Soil and plant factors
            SOIL = {
                'Sandy': {'water_factor': 1.40}, 'Sandy Loam': {'water_factor': 1.20},
                'Loam': {'water_factor': 1.00}, 'Silt': {'water_factor': 0.95},
                'Clay Loam': {'water_factor': 0.85}, 'Clay': {'water_factor': 0.75},
                'Peat': {'water_factor': 0.90}, 'Chalk': {'water_factor': 1.10},
            }
            soil = SOIL.get(soil_type, SOIL['Loam'])
            PUMP_FLOW_RATE = 10

            # Intelligence: season, crop profile, drying rate
            from datetime import datetime, timedelta
            today_eat = datetime.now()
            season = detect_season(today_eat.month)
            crop_profile = get_crop_profile(plant_type)

            # Fetch last 30 daily logs for drying rate analysis
            recent_logs = list(
                DailyAgriLog.objects
                .filter(user=request.user)
                .order_by('date')
                .values('avg_moisture', 'avg_temp', 'total_rain_mm')[:30]
            )
            drying = compute_drying_rate(recent_logs)

            def irrigation_plan(condition, temp, rain_prob):
                return compute_smart_irrigation(
                    temp=temp,
                    rain_prob=rain_prob,
                    condition=condition,
                    soil_water_factor=soil['water_factor'],
                    base_duration=base_duration,
                    crop_profile=crop_profile,
                    season=season,
                    drying=drying,
                    recent_logs=recent_logs,
                )

            # Calculate irrigation plans
            for day_data in forecast_list:
                plan = irrigation_plan(
                    day_data['condition'], 
                    day_data['temp_high'], 
                    day_data['rain_probability']
                )
                day_data['irrigation'] = plan

            today_plan = irrigation_plan(
                current_weather['condition'], 
                current_weather['temperature'],
                current_weather.get('rain_probability', 0)
            )
            current_weather['irrigation'] = today_plan

            # Write / update today's DailyAgriLog
            try:
                log_date = today_eat.date()
                log, _ = DailyAgriLog.objects.get_or_create(
                    user=request.user, date=log_date,
                    defaults={'season': season['key']}
                )
                log.avg_temp = current_weather['temperature']
                log.rain_prob = current_weather.get('rain_probability', 0)
                log.total_rain_mm = round(today_plan.get('rain_saving_l', 0) / 10, 2)
                log.water_used_l = today_plan.get('water_total_l', 0)
                log.season = season['key']
                # avg_moisture from latest sensor reading if available
                device = Device.objects.filter(user=request.user, status='Online').first()
                if device:
                    latest = SensorReading.objects.filter(device=device).first()
                    if latest and latest.soil_moisture is not None:
                        log.avg_moisture = latest.soil_moisture
                log.save()
            except Exception as e:
                print(f'DailyAgriLog write error: {e}')

            hourly = self._parse_hourly(forecast_data, today_plan)
            weekly_water = round(sum(d['irrigation']['water_total_l'] for d in forecast_list), 1)
            weekly_saving = round(sum(d['irrigation']['rain_saving_l'] for d in forecast_list), 1)

            # Log this weather access
            try:
                from api.models import WeatherAccessLog
                WeatherAccessLog.objects.create(
                    user=request.user,
                    lat=lat, lon=lon,
                    location=current_weather.get('location', ''),
                    success=True,
                )
            except Exception:
                pass

            return Response({
                'current': current_weather,
                'hourly': hourly,
                'forecast': forecast_list,
                'intelligence': {
                    'season': season,
                    'crop': {
                        'key': crop_profile['key'],
                        'label': crop_profile['label'],
                        'stress_temp': crop_profile['stress_temp_high'],
                        'stress_moisture': crop_profile['stress_moisture_low'],
                        'season_factor': crop_profile['season_adjust'].get(season['key'], 1.0),
                    },
                    'drying': drying,
                    'log_count': len(recent_logs),
                },
                'irrigation_settings': {
                    'base_duration_min': base_duration,
                    'soil_type': soil_type,
                    'plant_type': settings_obj.plant_type or 'General',
                    'pump_flow_rate': PUMP_FLOW_RATE,
                    'weekly_water_l': weekly_water,
                    'weekly_saving_l': weekly_saving,
                },
            })

        except Exception as e:
            print(f'[WeatherView] Error: {e}')
            import traceback
            traceback.print_exc()
            from datetime import datetime
            
            return Response({
                'detail': f'Weather service error: {str(e)}',
                'current': {
                    'condition': 'sunny', 'temperature': 24, 'humidity': 60,
                    'rain_probability': 10, 'wind_speed': 14, 'pressure': 1013,
                    'visibility': 10, 'feels_like': 26,
                    'description': 'Unable to fetch weather data',
                    'location': 'Unknown Location',
                    'updated_at': datetime.utcnow().isoformat() + 'Z',
                    'irrigation': {
                        'water_total_l': 10,
                        'pump_duration_min': 30,
                        'rain_saving_l': 0,
                        'reason': 'Service error - using default values',
                        'pump_times': [],
                    },
                },
                'forecast': [],
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    def _parse_current_weather(self, data):
        """Parse current weather API response"""
        from datetime import datetime
        if not data:
            return {
                'condition': 'sunny', 'temperature': 24, 'humidity': 60,
                'rain_probability': 10, 'wind_speed': 14, 'pressure': 1013,
                'visibility': 10, 'feels_like': 26,
                'description': 'Clear skies (offline data)',
                'location': 'Unknown Location',
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            }
            
        main = data.get('main', {})
        weather = data.get('weather', [{}])[0]
        wind = data.get('wind', {})
        
        condition_map = {
            'clear sky': 'sunny', 'few clouds': 'partly_cloudy',
            'scattered clouds': 'partly_cloudy', 'broken clouds': 'cloudy',
            'overcast clouds': 'cloudy', 'shower rain': 'rainy',
            'rain': 'rainy', 'thunderstorm': 'stormy', 'snow': 'snowy',
            'mist': 'foggy', 'fog': 'foggy'
        }
        
        description = weather.get('description', '').lower()
        condition = condition_map.get(description, 'sunny')
        
        return {
            'condition': condition,
            'temperature': round(main.get('temp', 0)),
            'humidity': main.get('humidity', 0),
            'rain_probability': 0,
            'wind_speed': round(wind.get('speed', 0) * 3.6),
            'pressure': main.get('pressure', 0),
            'visibility': round(data.get('visibility', 10000) / 1000),
            'feels_like': round(main.get('feels_like', 0)),
            'description': weather.get('description', '').title(),
            'location': data.get('name', 'Unknown'),
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }

    def _parse_forecast(self, data):
        """Parse forecast API response"""
        from datetime import datetime, timedelta
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        if not data or 'list' not in data:
            # Fallback forecast
            conditions = ['sunny', 'partly_cloudy', 'cloudy', 'rainy', 'sunny', 'partly_cloudy', 'sunny']
            temp_highs = [26, 24, 21, 19, 23, 25, 27]
            temp_lows = [16, 15, 14, 13, 15, 16, 17]
            rain_probs = [5, 20, 40, 75, 15, 10, 5]
            
            forecast = []
            now = datetime.now()
            for i in range(7):
                date = now + timedelta(days=i)
                forecast.append({
                    'day': days[date.weekday()],
                    'date': date.strftime('%Y-%m-%d'),
                    'condition': conditions[i],
                    'temp_high': temp_highs[i],
                    'temp_low': temp_lows[i],
                    'rain_probability': rain_probs[i]
                })
            return forecast
        
        # Parse real forecast data
        daily_data = {}
        condition_map = {
            'clear sky': 'sunny', 'few clouds': 'partly_cloudy',
            'scattered clouds': 'partly_cloudy', 'broken clouds': 'cloudy',
            'overcast clouds': 'cloudy', 'shower rain': 'rainy',
            'rain': 'rainy', 'thunderstorm': 'stormy', 'snow': 'snowy',
            'mist': 'foggy', 'fog': 'foggy'
        }
        
        for item in data['list'][:35]:
            dt = datetime.fromtimestamp(item['dt'])
            date_key = dt.strftime('%Y-%m-%d')
            
            if date_key not in daily_data:
                daily_data[date_key] = {
                    'day': days[dt.weekday()], 'date': date_key,
                    'temps': [], 'conditions': [], 'rain_probs': []
                }
            
            daily_data[date_key]['temps'].append(item['main']['temp'])
            
            weather = item.get('weather', [{}])[0]
            description = weather.get('description', '').lower()
            condition = condition_map.get(description, 'sunny')
            daily_data[date_key]['conditions'].append(condition)
            
            rain_prob = 0
            if 'rain' in item:
                rain_prob = min(100, item['rain'].get('3h', 0) * 20)
            elif condition in ['rainy', 'stormy']:
                rain_prob = 70
            elif condition == 'cloudy':
                rain_prob = 30
            elif condition == 'partly_cloudy':
                rain_prob = 15
            
            daily_data[date_key]['rain_probs'].append(rain_prob)
        
        forecast = []
        for date_key in sorted(daily_data.keys())[:7]:
            day_data = daily_data[date_key]
            conditions = day_data['conditions']
            condition = max(set(conditions), key=conditions.count) if conditions else 'sunny'
            
            forecast.append({
                'day': day_data['day'], 'date': date_key, 'condition': condition,
                'temp_high': round(max(day_data['temps'])) if day_data['temps'] else 25,
                'temp_low': round(min(day_data['temps'])) if day_data['temps'] else 15,
                'rain_probability': round(sum(day_data['rain_probs']) / len(day_data['rain_probs'])) if day_data['rain_probs'] else 10
            })
        
        # Fill remaining days if needed
        while len(forecast) < 7:
            base_date = datetime.now() + timedelta(days=len(forecast))
            forecast.append({
                'day': days[base_date.weekday()],
                'date': base_date.strftime('%Y-%m-%d'),
                'condition': 'sunny', 'temp_high': 25, 'temp_low': 15, 'rain_probability': 10
            })
        
        return forecast[:7]

    def _parse_hourly(self, data, today_plan):
        """Extract next 8 hours from forecast data"""
        from datetime import datetime
        if not data or 'list' not in data:
            return []
        
        condition_map = {
            'clear sky': 'sunny', 'few clouds': 'partly_cloudy',
            'scattered clouds': 'partly_cloudy', 'broken clouds': 'cloudy',
            'overcast clouds': 'cloudy', 'shower rain': 'rainy',
            'rain': 'rainy', 'thunderstorm': 'stormy', 'snow': 'snowy',
            'mist': 'foggy', 'fog': 'foggy'
        }
        pump_times = set(today_plan.get('pump_times', []))
        hours = []
        for item in data['list'][:8]:
            dt = datetime.fromtimestamp(item['dt'])
            hour_str = dt.strftime('%H:%M')
            weather = item.get('weather', [{}])[0]
            description = weather.get('description', '').lower()
            condition = condition_map.get(description, 'sunny')
            rain_prob = 0
            if 'rain' in item:
                rain_prob = min(100, item['rain'].get('3h', 0) * 20)
            elif condition in ['rainy', 'stormy']:
                rain_prob = 70
            elif condition == 'cloudy':
                rain_prob = 30
            # Check if pump runs within 30 min of this hour
            pump_active = False
            for pt in pump_times:
                ph, pm = map(int, pt.split(':'))
                diff = abs((dt.hour * 60 + dt.minute) - (ph * 60 + pm))
                if diff <= 30:
                    pump_active = True
                    break
            hours.append({
                'time': hour_str,
                'temp': round(item['main']['temp'], 1),
                'feels_like': round(item['main']['feels_like'], 1),
                'humidity': round(item['main']['humidity'], 1),
                'condition': condition,
                'description': weather.get('description', '').title(),
                'rain_probability': round(rain_prob, 1),
                'wind_speed': round(item['wind']['speed'] * 3.6, 1),
                'pump_active': pump_active,
            })
        return hours




class IntelligenceView(APIView):
    """Returns seasonal learning summary and crop intelligence for the frontend."""

    def get(self, request):
        from datetime import datetime
        from .intelligence import detect_season, get_crop_profile, compute_drying_rate

        settings_obj, _ = FarmSettings.objects.get_or_create(user=request.user)
        plant_type = (settings_obj.plant_type or 'general').strip().lower()

        season = detect_season(datetime.now().month)
        crop_profile = get_crop_profile(plant_type)

        recent_logs = list(
            DailyAgriLog.objects
            .filter(user=request.user)
            .order_by('date')
            .values('date', 'avg_moisture', 'avg_temp', 'total_rain_mm', 'water_used_l', 'season')[:30]
        )
        drying = compute_drying_rate(recent_logs)

        # Season history: group water_used_l by season
        from django.db.models import Avg, Sum
        season_summary = (
            DailyAgriLog.objects
            .filter(user=request.user)
            .values('season')
            .annotate(avg_temp=Avg('avg_temp'), avg_moisture=Avg('avg_moisture'), total_water=Sum('water_used_l'))
        )

        return Response({
            'season': season,
            'crop': {
                'key': crop_profile['key'],
                'label': crop_profile['label'],
                'stress_temp': crop_profile['stress_temp_high'],
                'stress_moisture': crop_profile['stress_moisture_low'],
                'water_demand_l_day': crop_profile['water_demand_l_day'],
                'season_factor': crop_profile['season_adjust'].get(season['key'], 1.0),
                'all_season_factors': crop_profile['season_adjust'],
            },
            'drying': drying,
            'season_history': list(season_summary),
            'recent_logs': [
                {
                    'date': str(l['date']), 'season': l['season'],
                    'avg_temp': l['avg_temp'], 'avg_moisture': l['avg_moisture'],
                    'total_rain_mm': l['total_rain_mm'], 'water_used_l': l['water_used_l'],
                }
                for l in recent_logs
            ],
            'log_count': len(recent_logs),
        })


class LocationSearchView(APIView):
    """Geocode a place name: Redis cache → DB cache → Nominatim. Admin-only."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import urllib.request, json as _json
        from .weather_cache import get_redis_client

        raw = request.GET.get('q', '').strip()
        if not raw:
            return Response([], status=status.HTTP_200_OK)

        query = raw.lower()
        cache_key = f'location:{query}'
        LOCATION_TTL = 60 * 60 * 24 * 30  # 30 days

        # 1. Check Redis
        redis_client = get_redis_client()
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    return Response(_json.loads(cached))
            except Exception:
                pass

        # 2. Check PostgreSQL
        cached_db = LocationCache.objects.filter(search_term=query).first()
        if cached_db:
            result = [{
                'display_name': cached_db.display_name,
                'lat': cached_db.latitude,
                'lon': cached_db.longitude,
            }]
            if redis_client:
                try:
                    redis_client.setex(cache_key, LOCATION_TTL, _json.dumps(result))
                except Exception:
                    pass
            return Response(result)

        # 3. Query Nominatim
        try:
            url = (
                f'https://nominatim.openstreetmap.org/search'
                f'?format=json&limit=5&q={urllib.request.quote(raw)}'
            )
            req = urllib.request.Request(url, headers={'User-Agent': 'EducFarm/1.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                results = _json.loads(r.read().decode())
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        if not results:
            return Response([])

        # 4. Save top result to PostgreSQL
        top = results[0]
        try:
            LocationCache.objects.get_or_create(
                search_term=query,
                defaults={
                    'display_name': top['display_name'],
                    'latitude':     float(top['lat']),
                    'longitude':    float(top['lon']),
                },
            )
        except Exception:
            pass

        # 5. Save all results to Redis
        formatted = [
            {
                'display_name': r['display_name'],
                'lat': float(r['lat']),
                'lon': float(r['lon']),
            }
            for r in results
        ]
        if redis_client:
            try:
                redis_client.setex(cache_key, LOCATION_TTL, _json.dumps(formatted))
            except Exception:
                pass

        return Response(formatted)


class PlantProfilesView(APIView):
    """Returns plant profiles — active only for users, all (including disabled) for admins."""

    def get(self, request):
        from .intelligence import CROP_PROFILES

        DEFAULT_SA = {
            'long_rains': 0.4, 'cool_dry': 0.85,
            'short_rains': 0.5, 'hot_dry': 1.3, 'transition': 1.0,
        }

        is_admin = request.user.is_staff

        # All DB profiles indexed by key
        all_db = {p.key: p for p in PlantProfile.objects.all()}

        result = []

        # 1. DB profiles — admins see all, users only see active
        for p in all_db.values():
            if not is_admin and not p.is_active:
                continue
            sa = {**DEFAULT_SA, **(p.season_adjust or {})}
            result.append({
                'id': p.id,
                'key': p.key,
                'label': p.label,
                'water_demand_l_day': p.water_demand_l_day,
                'stress_temp_high': p.stress_temp_high,
                'stress_moisture_low': p.stress_moisture_low,
                'root_depth_factor': p.root_depth_factor,
                'season_adjust': sa,
                'is_active': p.is_active,
                'is_builtin': p.is_builtin,
                'source': 'db',
            })

        # 2. Built-ins not yet in DB
        db_keys = set(all_db.keys())
        for key, cp in CROP_PROFILES.items():
            if key in db_keys:
                continue
            result.append({
                'id': None,
                'key': key,
                'label': cp['label'],
                'water_demand_l_day': cp['water_demand_l_day'],
                'stress_temp_high': cp['stress_temp_high'],
                'stress_moisture_low': cp['stress_moisture_low'],
                'root_depth_factor': cp['root_depth_factor'],
                'season_adjust': cp['season_adjust'],
                'is_active': True,
                'is_builtin': True,
                'source': 'builtin',
            })

        result.sort(key=lambda x: x['label'])
        return Response(result)


class WeatherLocationView(APIView):
    """Handle location-based weather queries and location search"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get weather location or search for locations"""
        import urllib.request
        import json
        from django.conf import settings as django_settings
        
        # Get search query from request
        search_query = request.GET.get('q', '').strip()
        
        if not search_query:
            # Return default location
            location = getattr(django_settings, 'DEFAULT_WEATHER_LOCATION', {
                'lat': 40.7128, 'lon': -74.0060, 'name': 'New York City', 'country': 'US'
            })
            return Response({
                'locations': [location],
                'status': 'success'
            })
        
        # Search for locations using geocoding API
        try:
            api_key = getattr(django_settings, 'OPENWEATHER_API_KEY', '')
            geo_url = f"https://api.openweathermap.org/geo/1.0/direct?q={search_query}&limit=5&appid={api_key}"
            
            with urllib.request.urlopen(geo_url, timeout=10) as response:
                locations_data = json.loads(response.read().decode())
            
            # Format results
            locations = [
                {
                    'name': loc.get('name', ''),
                    'country': loc.get('country', ''),
                    'lat': loc.get('lat', 0),
                    'lon': loc.get('lon', 0),
                    'state': loc.get('state', '')
                }
                for loc in locations_data
            ]
            
            return Response({
                'locations': locations,
                'status': 'success',
                'count': len(locations)
            })
            
        except Exception as e:
            return Response({
                'locations': [],
                'status': 'error',
                'message': str(e),
                'count': 0
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ──── Push Notifications ────────────────────────────────────────


class DeviceActivateView(APIView):
    """
    Hardware calls this on first boot to exchange (device_id + pairing_code) for secret_key.
    GET /api/device/activate/?device_id=X&pairing_code=Y
    - If device exists and pairing_code matches → return secret_key.
    - If device does NOT exist → auto-create it with a generated secret_key,
      mark is_paired=False so the user still needs to pair it in the app.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        import uuid
        device_id    = request.GET.get('device_id', '').strip()
        pairing_code = request.GET.get('pairing_code', '').strip()

        if not device_id or not pairing_code:
            return Response(
                {'error': 'device_id and pairing_code are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device = Device.objects.filter(device_id=device_id).first()

        if not device:
            # Auto-create device record so hardware can start posting data
            # User still needs to pair it in the app to see data on their dashboard
            from users.models import User
            secret_key = uuid.uuid4().hex + uuid.uuid4().hex  # 64-char random key
            placeholder = User.objects.filter(is_staff=True).first() or User.objects.first()
            device = Device.objects.create(
                device_id=device_id,
                pairing_code=pairing_code,
                secret_key=secret_key,
                device_name=f'EducFarm {device_id[-6:]}',
                is_paired=False,
                user=placeholder,
            )
            return Response({
                'secret_key': device.secret_key,
                'device_name': device.device_name,
                'is_paired': False,
                'created': True,
            })

        if device.pairing_code != pairing_code:
            return Response(
                {'error': 'Invalid pairing_code'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response({
            'secret_key': device.secret_key,
            'device_name': device.device_name,
            'is_paired': device.is_paired,
            'created': False,
        })


class SMSSettingsView(APIView):
    """
    GET  /api/sms-settings/  — return current SMS config
    POST /api/sms-settings/  — create or update SMS config
    """
    def get(self, request):
        obj, _ = SMSSettings.objects.get_or_create(user=request.user)
        return Response(SMSSettingsSerializer(obj).data)

    def post(self, request):
        obj, _ = SMSSettings.objects.get_or_create(user=request.user)
        serializer = SMSSettingsSerializer(obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        instance = serializer.save()
        if 'phone_numbers' in request.data:
            try:
                SMSSettings.objects.filter(pk=instance.pk).update(phones_dirty=True)
            except Exception:
                pass
        instance.refresh_from_db()
        return Response(SMSSettingsSerializer(instance).data)


class DeviceSettingsView(APIView):
    """
    Hardware polls this to get farmer-configured thresholds.
    Auth: device_id + secret_key (no user token needed).
    GET /api/device/settings/?device_id=X&secret_key=Y
    Returns moisture_min and moisture_critical_low from the device owner's FarmSettings.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        device_id  = request.GET.get('device_id', '').strip()
        secret_key = request.GET.get('secret_key', '').strip()

        if not device_id or not secret_key:
            return Response(
                {'error': 'device_id and secret_key are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device = Device.objects.filter(
            device_id=device_id.strip(), secret_key=secret_key.strip()
        ).first()
        if not device:
            return Response(
                {'error': 'Invalid device credentials'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        fs, _ = FarmSettings.objects.get_or_create(user=device.user)
        sms, _ = SMSSettings.objects.get_or_create(user=device.user)

        try:
            send_phones = sms.phones_dirty
            if send_phones:
                SMSSettings.objects.filter(pk=sms.pk).update(phones_dirty=False)
        except Exception:
            send_phones = True  # migration not yet run — always send

        return Response({
            'moisture_min':          int(fs.moisture_min),
            'moisture_critical_low': int(fs.moisture_critical_low),
            'irrigation_duration':   int(fs.irrigation_duration),
            'sms_enabled':           sms.sms_enabled,
            'phones_dirty':          send_phones,
            'phone_numbers':         sms.phone_numbers if send_phones else [],
            'pump_alerts':           sms.pump_alerts,
            'weather_alerts':        sms.weather_alerts,
            'low_water_alerts':      sms.low_water_alerts,
            'sensor_failure_alerts': sms.sensor_failure_alerts,
        })


class DeviceWeatherView(APIView):
    """
    Hardware calls this to get weather + rain forecast.
    Auth: device_id + secret_key.
    GET /api/device/weather/?device_id=X&secret_key=Y&lat=L&lon=N
    Returns: rain_pct, weather_desc, rain_time (HH:MM of first rainy slot or empty)
    """
    permission_classes = [AllowAny]

    def get(self, request):
        import urllib.request, json as _json

        device_id  = request.GET.get('device_id', '').strip()
        secret_key = request.GET.get('secret_key', '').strip()
        if not device_id or not secret_key:
            return Response({'error': 'device_id and secret_key required'}, status=status.HTTP_400_BAD_REQUEST)
        device = Device.objects.filter(device_id=device_id, secret_key=secret_key).first()
        if not device:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

        lat = request.GET.get('lat')
        lon = request.GET.get('lon')

        # Fall back to FarmSettings location if no coords supplied
        if not lat or not lon:
            fs = FarmSettings.objects.filter(user=device.user).first()
            if fs:
                lat = fs.admin_weather_lat or fs.weather_lat
                lon = fs.admin_weather_lon or fs.weather_lon

        if not lat or not lon:
            return Response({'error': 'No location available'}, status=status.HTTP_404_NOT_FOUND)

        api_key = getattr(settings, 'OPENWEATHER_API_KEY', '').strip()
        if not api_key:
            return Response({'error': 'Weather API not configured'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            url = (
                f'https://api.openweathermap.org/data/2.5/forecast'
                f'?lat={lat}&lon={lon}&cnt=8&appid={api_key}&units=metric'
            )
            req = urllib.request.Request(url, headers={'User-Agent': 'EducFarm/1.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = _json.loads(r.read().decode())
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        slots = data.get('list', [])
        if not slots:
            return Response({'error': 'No forecast data'}, status=status.HTTP_502_BAD_GATEWAY)

        first = slots[0]
        rain_pct  = int(first.get('pop', 0) * 100)
        desc      = ''
        weather   = first.get('weather', [{}])[0]
        desc_raw  = weather.get('description', '')
        if desc_raw:
            desc = desc_raw[0].upper() + desc_raw[1:]

        # Find first slot where rain probability >= 60%
        rain_time = ''
        for slot in slots:
            if slot.get('pop', 0) >= 0.6:
                from datetime import datetime
                dt = datetime.utcfromtimestamp(slot['dt'])
                # Adjust to UTC+3 (East Africa Time)
                from datetime import timedelta
                dt_eat = dt + timedelta(hours=3)
                rain_time = dt_eat.strftime('%H:%M')
                break

        return Response({
            'rain_pct':     rain_pct,
            'weather_desc': desc,
            'rain_time':    rain_time,   # HH:MM in EAT, empty string if no rain expected
        })


class GPSFallbackView(APIView):
    """
    ESP32 calls this when A9G GPS fails.
    Returns saved lat/lon from FarmSettings for the device owner.
    Auth: device_id + secret_key (same as SensorIngestView).
    GET /api/device/gps-fallback/?device_id=X&secret_key=Y
    """
    permission_classes = [AllowAny]

    def get(self, request):
        device_id  = request.GET.get("device_id", "").strip()
        secret_key = request.GET.get("secret_key", "").strip()

        if not device_id or not secret_key:
            return Response(
                {"error": "device_id and secret_key are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device = Device.objects.filter(
            device_id=device_id, secret_key=secret_key
        ).first()

        if not device:
            return Response(
                {"error": "Invalid device credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Priority 1: admin-set weather location
        fs = FarmSettings.objects.filter(user=device.user).first()
        if fs:
            if fs.admin_weather_lat is not None and fs.admin_weather_lon is not None:
                return Response({
                    "lat":   fs.admin_weather_lat,
                    "lon":   fs.admin_weather_lon,
                    "place": fs.admin_weather_location_name or "Admin Location",
                    "source": "admin",
                })
            if fs.weather_lat is not None and fs.weather_lon is not None:
                return Response({
                    "lat":   fs.weather_lat,
                    "lon":   fs.weather_lon,
                    "place": fs.weather_location_name or "Farm Location",
                    "source": "farm_settings",
                })

        # Priority 2: latest LocationCache entry (any cached search)
        cached = LocationCache.objects.order_by("-created_at").first()
        if cached:
            return Response({
                "lat":   cached.latitude,
                "lon":   cached.longitude,
                "place": cached.display_name,
                "source": "location_cache",
            })

        return Response(
            {"error": "No location data available in backend"},
            status=status.HTTP_404_NOT_FOUND,
        )


class VapidKeyView(APIView):
    """Get VAPID public key for push subscriptions"""
    permission_classes = [AllowAny]

    def get(self, request):
        from django.conf import settings
        vapid_key = getattr(settings, 'VAPID_PUBLIC_KEY', '')
        return Response({
            'vapid_key': vapid_key,
        })


class PushSubscribeView(APIView):
    """Subscribe user to push notifications"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import PushSubscription
        
        endpoint = request.data.get('endpoint')
        auth = request.data.get('auth')
        p256dh = request.data.get('p256dh')
        
        if not all([endpoint, auth, p256dh]):
            return Response(
                {'detail': 'Missing required subscription fields'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            subscription, created = PushSubscription.objects.get_or_create(
                endpoint=endpoint,
                defaults={
                    'user': request.user,
                    'auth': auth,
                    'p256dh': p256dh,
                }
            )
            
            if not created:
                # Update existing subscription
                subscription.auth = auth
                subscription.p256dh = p256dh
                subscription.user = request.user
                subscription.save()
            
            return Response({
                'status': 'subscribed',
                'endpoint': endpoint[:50] + '...',
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class PushUnsubscribeView(APIView):
    """Unsubscribe user from push notifications"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import PushSubscription
        
        endpoint = request.data.get('endpoint')
        
        if not endpoint:
            return Response(
                {'detail': 'Endpoint required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            subscription = PushSubscription.objects.get(
                endpoint=endpoint,
                user=request.user
            )
            subscription.delete()
            
            return Response({
                'status': 'unsubscribed',
            })
        
        except PushSubscription.DoesNotExist:
            return Response(
                {'detail': 'Subscription not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class BadgeView(APIView):
    """Get unread notification count for badge"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        unread_count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).count()
        
        return Response({
            'unread_count': unread_count,
        })


class TestPushView(APIView):
    """Send a test push notification"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .push_utils import send_test_push
        
        result = send_test_push(request.user)
        
        return Response({
            'status': 'sent',
            'success': result['success'],
            'failed': result['failed'],
            'errors': result['errors'],
        })
