"""
Push notification utilities for Web Push Protocol (RFC 8188)
"""
import json
import logging
from pywebpush import webpush, WebPushException
from django.conf import settings
from .models import PushSubscription

logger = logging.getLogger(__name__)


def get_vapid_keys():
    """Get VAPID keys from settings or environment."""
    return {
        'subject': getattr(settings, 'VAPID_SUBJECT', 'mailto:admin@educfarm.com'),
        'publicKey': getattr(settings, 'VAPID_PUBLIC_KEY', ''),
        'privateKey': getattr(settings, 'VAPID_PRIVATE_KEY', ''),
    }


def send_push_to_user(user, title, body, badge_count=None, data=None, icon=None):
    """
    Send push notification to all subscribed devices for a user.
    
    Args:
        user: User object
        title: Notification title
        body: Notification body
        badge_count: Optional unread notification count
        data: Optional extra data dict
        icon: Optional icon URL
    
    Returns:
        dict with success count and failed subscriptions
    """
    subscriptions = PushSubscription.objects.filter(user=user)
    
    if not subscriptions.exists():
        logger.info(f'No push subscriptions for user {user.email}')
        return {'success': 0, 'failed': 0, 'errors': []}
    
    vapid = get_vapid_keys()
    if not vapid['publicKey'] or not vapid['privateKey']:
        logger.warning('VAPID keys not configured')
        return {'success': 0, 'failed': subscriptions.count(), 'errors': ['VAPID not configured']}
    
    payload = {
        'title': title,
        'body': body,
        'icon': icon or '/EducFarm/icons/pwa-192.png',
        'badge': '/EducFarm/icons/pwa-192.png',
        'data': data or {},
    }
    
    if badge_count is not None:
        payload['badge_count'] = badge_count
    
    success_count = 0
    failed_count = 0
    errors = []
    failed_endpoints = []
    
    for sub in subscriptions:
        try:
            subscription_info = {
                'endpoint': sub.endpoint,
                'keys': {
                    'p256dh': sub.p256dh,
                    'auth': sub.auth,
                }
            }
            
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload),
                vapid_private_key=vapid['privateKey'],
                vapid_claims={'sub': vapid['subject']},
                ttl=3600,
            )
            
            success_count += 1
            logger.info(f'Push sent to {user.email}')
            
        except WebPushException as e:
            failed_count += 1
            failed_endpoints.append(sub.endpoint)
            error_msg = str(e)
            logger.error(f'Push failed for {user.email}: {error_msg}')
            errors.append(error_msg)
            
            # Delete subscription if endpoint is invalid (410 Gone)
            if 'Unexpected HTTP' in error_msg and '410' in error_msg:
                logger.info(f'Deleting invalid subscription for {user.email}')
                sub.delete()
        
        except Exception as e:
            failed_count += 1
            failed_endpoints.append(sub.endpoint)
            error_msg = str(e)
            logger.error(f'Unexpected error sending push to {user.email}: {error_msg}')
            errors.append(error_msg)
    
    return {
        'success': success_count,
        'failed': failed_count,
        'failed_endpoints': failed_endpoints,
        'errors': errors,
    }


def send_test_push(user):
    """Send a test push notification."""
    return send_push_to_user(
        user=user,
        title='🧪 Test Notification',
        body='This is a test push notification from EducFarm.',
        data={'test': True},
    )
