import requests
from django.conf import settings


def send_sms(phone: str, message: str) -> bool:
    api_key = getattr(settings, 'TEXTBEE_API_KEY', '')
    device_id = getattr(settings, 'TEXTBEE_DEVICE_ID', '')
    if not api_key or not device_id:
        return False
    try:
        response = requests.post(
            f'https://api.textbee.dev/api/v1/gateway/devices/{device_id}/send-sms',
            headers={'x-api-key': api_key},
            json={'receivers': [phone], 'message': message},
            timeout=10,
        )
        return response.status_code == 201
    except Exception:
        return False


def send_welcome_sms(name: str, phone: str) -> bool:
    if not phone:
        return False
    message = f"Hi {name}, welcome to Majo Gadgets! 🎉 Explore the latest gadgets and enjoy exclusive deals. Shop now at majogadgets.com"
    return send_sms(phone, message)
