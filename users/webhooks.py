import base64
import binascii
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import EmailDelivery

logger = logging.getLogger(__name__)
SIGNATURE_TOLERANCE_SECONDS = 300


def _has_valid_resend_signature(request):
    secret = settings.RESEND_WEBHOOK_SECRET
    message_id = request.headers.get('svix-id', '')
    timestamp = request.headers.get('svix-timestamp', '')
    signature = request.headers.get('svix-signature', '')
    if not secret or not message_id or not timestamp or not signature:
        return False

    try:
        timestamp_seconds = int(timestamp)
        signing_key = base64.b64decode(secret.removeprefix('whsec_'), validate=True)
    except (ValueError, TypeError, binascii.Error):
        return False

    if abs(timezone.now().timestamp() - timestamp_seconds) > SIGNATURE_TOLERANCE_SECONDS:
        return False

    signed_content = b'.'.join((message_id.encode(), timestamp.encode(), request.body))
    expected_signature = base64.b64encode(
        hmac.new(signing_key, signed_content, hashlib.sha256).digest()
    ).decode()
    return any(
        version == 'v1' and hmac.compare_digest(value, expected_signature)
        for entry in signature.split()
        if ',' in entry
        for version, value in (entry.split(',', 1),)
    )


class ResendWebhookView(APIView):
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        if not settings.RESEND_WEBHOOK_SECRET:
            logger.error('Rejected Resend webhook because RESEND_WEBHOOK_SECRET is not configured')
            return Response(
                {'detail': 'Email webhook is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not _has_valid_resend_signature(request):
            logger.warning('Rejected Resend webhook with an invalid signature')
            return Response({'detail': 'Invalid webhook signature.'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            event = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response({'detail': 'Invalid JSON payload.'}, status=status.HTTP_400_BAD_REQUEST)

        event_type = event.get('type') if isinstance(event, dict) else None
        status_by_event = {
            'email.sent': 'sent',
            'email.delivered': 'delivered',
            'email.bounced': 'bounced',
            'email.failed': 'failed',
        }
        new_status = status_by_event.get(event_type)
        if not new_status:
            return Response({'detail': 'Event ignored.'}, status=status.HTTP_200_OK)

        data = event.get('data')
        provider_message_id = data.get('email_id') if isinstance(data, dict) else None
        if not provider_message_id:
            return Response({'detail': 'Missing email ID.'}, status=status.HTTP_400_BAD_REQUEST)

        updates = {
            'status': new_status,
            'updated_at': timezone.now(),
        }
        if new_status == 'failed':
            updates['error_type'] = 'ProviderDeliveryFailed'
        elif new_status in ('sent', 'delivered'):
            updates['error_type'] = ''

        updated_count = EmailDelivery.objects.filter(
            provider_message_id=provider_message_id,
        ).update(**updates)
        if not updated_count:
            logger.warning('Resend webhook references unknown email delivery %s', provider_message_id)
            return Response({'detail': 'Email delivery not found.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        logger.info(
            'Updated email delivery status: provider_message_id=%s status=%s',
            provider_message_id,
            new_status,
        )
        return Response({'status': new_status}, status=status.HTTP_200_OK)
