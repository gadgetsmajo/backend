import logging
import secrets
import base64
import hashlib
import json
import math
import uuid
from datetime import timedelta
from urllib.parse import urlparse
from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from .serializers import RegisterSerializer, UserSerializer, UpdateProfileSerializer, CartItemSerializer, WishlistItemSerializer, NotificationSerializer
from .models import CartItem, WishlistItem, Notification, UserBehaviour, SupportConversation, SupportConversationStaffPresence, SupportEncryptionBackup, SupportEncryptionKey, SupportMessage, EmailMfaChallenge, EmailMfaTrustedDevice
from .emails import send_welcome_email, send_password_reset_email, send_password_changed_email, send_login_verification_email, send_signin_alert_email, send_admin_new_support_message_email
from .sms import send_welcome_sms
from .authentication import requires_email_mfa

User = get_user_model()
logger = logging.getLogger(__name__)
MFA_CODE_LIFETIME = timedelta(minutes=10)
MFA_TRUST_LIFETIME = timedelta(days=7)
MFA_MAX_ATTEMPTS = 5
MFA_MAX_SENDS = 3
MFA_SEND_WINDOW = timedelta(minutes=15)
MFA_RESEND_COOLDOWN = timedelta(seconds=30)


def _issue_tokens(user, email_mfa_verified=False):
    refresh = RefreshToken.for_user(user)
    if email_mfa_verified:
        refresh['email_mfa_verified'] = True
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


def _mask_email(email):
    local, separator, domain = email.partition('@')
    return f'{local[:1]}***@{domain}' if separator else 'your registered email'


def _signin_device_name(request):
    supplied_name = request.data.get('device_name')
    if isinstance(supplied_name, str):
        supplied_name = supplied_name.strip()
        if supplied_name and len(supplied_name) <= 120 and all(char.isprintable() for char in supplied_name):
            return supplied_name

    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    if 'iphone' in user_agent:
        device = 'iPhone'
    elif 'ipad' in user_agent:
        device = 'iPad'
    elif 'android' in user_agent:
        device = 'Android device'
    elif 'windows' in user_agent:
        device = 'Windows computer'
    elif 'mac os' in user_agent or 'macintosh' in user_agent:
        device = 'Mac'
    elif 'linux' in user_agent:
        device = 'Linux computer'
    else:
        device = 'Unknown device'

    if 'edg/' in user_agent:
        browser = 'Edge'
    elif 'opr/' in user_agent:
        browser = 'Opera'
    elif 'firefox/' in user_agent:
        browser = 'Firefox'
    elif 'chrome/' in user_agent or 'crios/' in user_agent:
        browser = 'Chrome'
    elif 'safari/' in user_agent:
        browser = 'Safari'
    else:
        browser = ''
    return f'{device} ({browser})' if browser else device


def _signin_location(data):
    if not isinstance(data, dict):
        return 'Unavailable (location permission not granted or unavailable)'
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return 'Unavailable (location permission not granted or unavailable)'
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return 'Unavailable (location permission not granted or unavailable)'
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return 'Unavailable (location permission not granted or unavailable)'
    return f'{latitude:.3f}, {longitude:.3f}'


def _send_signin_alert(user, device_name, location):
    try:
        send_signin_alert_email(
            user.name,
            user.email,
            device_name,
            _signin_location(location),
            timezone.localtime().strftime('%Y-%m-%d %H:%M %Z'),
        )
    except Exception:
        logger.exception('Failed to deliver sign-in alert for user %s', user.pk)
        return False
    return True


def _send_mfa_code(challenge, code):
    try:
        send_login_verification_email(challenge.user.name, challenge.user.email, code)
    except Exception:
        logger.exception('Failed to deliver email MFA code for user %s', challenge.user_id)
        raise


def _start_email_mfa(user, trusted_device_token=None, request=None):
    if isinstance(trusted_device_token, str) and trusted_device_token:
        token_hash = hashlib.sha256(trusted_device_token.encode('utf-8')).hexdigest()
        trusted_device = EmailMfaTrustedDevice.objects.filter(
            user=user, token_hash=token_hash, expires_at__gt=timezone.now(),
        ).first()
        if trusted_device:
            if not _send_signin_alert(user, _signin_device_name(request), request.data.get('signin_location')):
                return Response(
                    {'detail': 'Could not send a sign-in security alert. Please try again shortly.'},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return Response(_issue_tokens(user, email_mfa_verified=True))
        EmailMfaTrustedDevice.objects.filter(user=user, token_hash=token_hash).delete()

    now = timezone.now()
    recent_challenges = EmailMfaChallenge.objects.filter(user=user, created_at__gte=now - MFA_SEND_WINDOW)
    if sum(recent_challenges.values_list('send_count', flat=True)) >= MFA_MAX_SENDS:
        return Response(
            {'detail': 'Too many verification codes requested. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    EmailMfaChallenge.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=now)
    code = f'{secrets.randbelow(1_000_000):06d}'
    challenge = EmailMfaChallenge.objects.create(
        user=user,
        code_hash=make_password(code),
        device_name=_signin_device_name(request),
        expires_at=now + MFA_CODE_LIFETIME,
        last_sent_at=now,
    )
    try:
        _send_mfa_code(challenge, code)
    except Exception:
        challenge.delete()
        return Response(
            {'detail': 'Could not send a verification code. Please try again shortly.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({
        'mfa_required': True,
        'challenge_id': str(challenge.challenge_id),
        'email_hint': _mask_email(user.email),
    }, status=status.HTTP_200_OK)


def _verified_login_response(user, request):
    if not requires_email_mfa(user):
        return Response(_issue_tokens(user))
    return _start_email_mfa(user, request.data.get('trusted_device'), request)


class EmailMfaVerifyView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        challenge_id = request.data.get('challenge_id')
        code = request.data.get('code', '')
        if not isinstance(code, str) or not code.isdigit() or len(code) != 6:
            return Response({'detail': 'Enter the six-digit verification code.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            challenge = EmailMfaChallenge.objects.select_related('user').get(
                challenge_id=challenge_id, consumed_at__isnull=True,
            )
        except (EmailMfaChallenge.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'This verification request is invalid or expired. Sign in again.'}, status=status.HTTP_400_BAD_REQUEST)

        if not challenge.user.is_active:
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=['consumed_at'])
            return Response({'detail': 'This account is inactive.'}, status=status.HTTP_401_UNAUTHORIZED)

        if challenge.expires_at <= timezone.now() or challenge.failed_attempts >= MFA_MAX_ATTEMPTS:
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=['consumed_at'])
            return Response({'detail': 'This verification code has expired. Sign in again for a new code.'}, status=status.HTTP_400_BAD_REQUEST)
        if not check_password(code, challenge.code_hash):
            challenge.failed_attempts += 1
            if challenge.failed_attempts >= MFA_MAX_ATTEMPTS:
                challenge.consumed_at = timezone.now()
            challenge.save(update_fields=['failed_attempts', 'consumed_at'])
            return Response({'detail': 'The verification code is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=['consumed_at'])
        if not _send_signin_alert(
            challenge.user,
            challenge.device_name,
            request.data.get('signin_location'),
        ):
            return Response(
                {'detail': 'Could not send a sign-in security alert. Please try again shortly.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        result = _issue_tokens(challenge.user, email_mfa_verified=True)
        if request.data.get('remember_device') is True:
            device_token = secrets.token_urlsafe(32)
            EmailMfaTrustedDevice.objects.create(
                user=challenge.user,
                token_hash=hashlib.sha256(device_token.encode('utf-8')).hexdigest(),
                expires_at=timezone.now() + MFA_TRUST_LIFETIME,
            )
            result['trusted_device'] = device_token
        return Response(result)


class EmailMfaResendView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        try:
            challenge = EmailMfaChallenge.objects.select_related('user').get(
                challenge_id=request.data.get('challenge_id'), consumed_at__isnull=True,
            )
        except (EmailMfaChallenge.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'This verification request is invalid or expired. Sign in again.'}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        if challenge.expires_at <= now or challenge.failed_attempts >= MFA_MAX_ATTEMPTS:
            challenge.consumed_at = now
            challenge.save(update_fields=['consumed_at'])
            return Response({'detail': 'This verification request has expired. Sign in again.'}, status=status.HTTP_400_BAD_REQUEST)
        if challenge.send_count >= MFA_MAX_SENDS:
            return Response({'detail': 'The resend limit has been reached. Sign in again later.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if challenge.last_sent_at + MFA_RESEND_COOLDOWN > now:
            return Response({'detail': 'Wait 30 seconds before requesting another code.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        code = f'{secrets.randbelow(1_000_000):06d}'
        try:
            _send_mfa_code(challenge, code)
        except Exception:
            return Response({'detail': 'Could not send a verification code. Please try again shortly.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        challenge.code_hash = make_password(code)
        challenge.last_sent_at = now
        challenge.send_count += 1
        challenge.save(update_fields=['code_hash', 'last_sent_at', 'send_count'])
        return Response({'detail': f'A new verification code was sent to {_mask_email(challenge.user.email)}.'})


class EmailMfaTokenRefreshView(TokenRefreshView):
    from .authentication import MfaTokenRefreshSerializer

    serializer_class = MfaTokenRefreshSerializer


def _store_google_avatar(user, picture_url):
    if user.avatar or not picture_url:
        return

    parsed_url = urlparse(picture_url)
    hostname = parsed_url.hostname or ''
    if parsed_url.scheme != 'https' or not (
        hostname == 'googleusercontent.com' or hostname.endswith('.googleusercontent.com')
    ):
        return

    try:
        import cloudinary.uploader
        result = cloudinary.uploader.upload(picture_url, folder='avatars/')
        public_id = result.get('public_id')
        if public_id:
            user.avatar = public_id
            user.save(update_fields=['avatar'])
    except Exception:
        logger.exception('Failed to save Google profile photo for user %s', user.pk)


class LoginView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')
        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response({'detail': 'No active account found with the given credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        return _verified_login_response(user, request)


class AdminUsersView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        users = User.objects.all().order_by('-id')
        return Response(UserSerializer(users, many=True).data)

    def post(self, request):
        password = request.data.get('password')
        if not password:
            return Response({'password': 'Password is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.create_user(
                email=request.data.get('email', ''),
                password=password,
                name=request.data.get('name', ''),
                phone=request.data.get('phone', ''),
            )
            if request.data.get('is_staff'):
                user.is_staff = True
                user.save()
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class AdminUserDetailView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def patch(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = UpdateProfileSerializer(user, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(user).data)

    def delete(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _support_message_data(message):
    try:
        encryption_version = json.loads(message.body).get('version')
    except (json.JSONDecodeError, AttributeError):
        encryption_version = None
    return {
        'id': message.id,
        'conversation_id': message.conversation_id,
        'sender_id': message.sender_id,
        'sender_name': message.sender.name,
        'is_staff': message.sender.is_staff,
        'body': message.body,
        'encryption_version': encryption_version,
        'is_read': message.is_read,
        'created_at': message.created_at,
    }


def _is_typing(timestamp):
    return bool(timestamp and timestamp >= timezone.now() - timedelta(seconds=8))


def _support_presence_status(conversation):
    now = timezone.now()
    presence = conversation.staff_presence.all()
    if presence.filter(last_seen_at__gte=now - timedelta(seconds=15)).exists():
        return 'joined'
    if presence.filter(first_joined_at__isnull=False).exists():
        return 'left'
    return 'waiting'


def _set_support_staff_presence(conversation, staff, is_viewing):
    now = timezone.now()
    presence, _ = SupportConversationStaffPresence.objects.get_or_create(
        conversation=conversation,
        staff=staff,
    )
    presence.last_seen_at = now if is_viewing else None
    if is_viewing and presence.first_joined_at is None:
        presence.first_joined_at = now
    presence.save(update_fields=['first_joined_at', 'last_seen_at'])


def _support_staff_keys():
    support_staff_ids = [
        user.id
        for user in User.objects.filter(is_active=True, is_staff=True).only('id', 'is_superuser', 'assigned_pages')
        if user.is_superuser or not user.assigned_pages or 'Support' in user.assigned_pages
    ]
    return SupportEncryptionKey.objects.filter(user_id__in=support_staff_ids).select_related('user')


def _support_encryption_key_data(key):
    return {
        'key_id': str(key.id),
        'device_id': str(key.device_id),
        'user_id': key.user_id,
        'is_staff': key.user.is_staff,
        'public_key': key.public_key,
        'created_at': key.created_at,
    }


class SupportEncryptionKeysView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        keys = _support_staff_keys()
        if request.user.is_staff:
            if not IsSupportStaff().has_permission(request, self):
                return Response(status=status.HTTP_403_FORBIDDEN)
            user_id = request.query_params.get('user_id')
            if user_id:
                try:
                    customer = User.objects.get(pk=user_id, is_staff=False, is_active=True)
                except (User.DoesNotExist, ValueError):
                    return Response({'detail': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)
                keys = keys | SupportEncryptionKey.objects.filter(user=customer).select_related('user')
            else:
                keys = keys | SupportEncryptionKey.objects.filter(user=request.user).select_related('user')
        else:
            keys = keys | SupportEncryptionKey.objects.filter(user=request.user).select_related('user')

        return Response({'keys': [_support_encryption_key_data(key) for key in keys.order_by('user_id', 'id')]})

    def post(self, request):
        device_id = request.data.get('device_id')
        public_key = request.data.get('public_key')
        try:
            device_id = uuid.UUID(str(device_id))
            decoded_key = base64.b64decode(public_key, validate=True)
        except (ValueError, TypeError):
            return Response({'detail': 'A valid device ID and base64 public key are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(decoded_key) != 32:
            return Response({'public_key': 'Public keys must be 32 bytes.'}, status=status.HTTP_400_BAD_REQUEST)

        key, _ = SupportEncryptionKey.objects.update_or_create(
            user=request.user,
            device_id=device_id,
            defaults={'public_key': public_key},
        )
        return Response(_support_encryption_key_data(key), status=status.HTTP_201_CREATED)

    def delete(self, request):
        try:
            device_id = uuid.UUID(str(request.data.get('device_id')))
        except (ValueError, TypeError):
            return Response({'device_id': 'A valid device ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = SupportEncryptionKey.objects.filter(user=request.user, device_id=device_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)


class SupportEncryptionBackupView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    required_iterations = 600_000

    def get(self, request):
        backup = SupportEncryptionBackup.objects.filter(user=request.user).first()
        return Response({'backup': backup.payload if backup else None})

    def put(self, request):
        payload = request.data.get('backup')
        if not isinstance(payload, dict):
            return Response({'detail': 'An encrypted support key backup is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if (
            type(payload.get('version')) is not int
            or payload.get('version') != 1
            or payload.get('kdf') != 'PBKDF2-SHA256'
            or type(payload.get('iterations')) is not int
            or payload.get('iterations') != self.required_iterations
        ):
            return Response({'detail': 'Unsupported support key backup format.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            device_id = uuid.UUID(str(payload.get('device_id')))
        except (ValueError, TypeError, AttributeError):
            return Response({'detail': 'Support key backup device ID is invalid.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            salt = base64.b64decode(payload.get('salt'), validate=True)
            ciphertext = base64.b64decode(payload.get('ciphertext'), validate=True)
        except (ValueError, TypeError):
            return Response({'detail': 'Support key backup data must be base64 encoded.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(salt) != 16 or len(ciphertext) < 28 or len(ciphertext) > 16_384:
            return Response({'detail': 'Support key backup data has invalid size.'}, status=status.HTTP_400_BAD_REQUEST)

        current = SupportEncryptionBackup.objects.filter(user=request.user).first()
        if current and current.payload.get('device_id') != str(device_id):
            return Response(
                {'detail': 'A different encryption identity is already backed up. Restore it before replacing this device key.'},
                status=status.HTTP_409_CONFLICT,
            )

        backup, _ = SupportEncryptionBackup.objects.update_or_create(
            user=request.user,
            defaults={'payload': {
                'version': payload['version'],
                'kdf': payload['kdf'],
                'iterations': payload['iterations'],
                'device_id': str(device_id),
                'salt': payload['salt'],
                'ciphertext': payload['ciphertext'],
            }},
        )
        return Response({'backup': backup.payload, 'updated_at': backup.updated_at})


def _validate_support_ciphertext(request, recipient_user_id):
    envelope = request.data.get('envelope')
    if not isinstance(envelope, dict) or envelope.get('version') != 1:
        return None, Response({'detail': 'Messages must use the supported encrypted envelope.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        sender_key_id = uuid.UUID(str(envelope.get('sender_key_id')))
    except (ValueError, TypeError):
        return None, Response({'detail': 'A valid sender key is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not SupportEncryptionKey.objects.filter(id=sender_key_id, user=request.user).exists():
        return None, Response({'detail': 'Register this device encryption key before sending.'}, status=status.HTTP_400_BAD_REQUEST)

    entries = envelope.get('recipients')
    if not isinstance(entries, list) or not entries or len(entries) > 100:
        return None, Response({'detail': 'Encrypted messages must include valid recipients.'}, status=status.HTTP_400_BAD_REQUEST)

    included_ids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return None, Response({'detail': 'Invalid encrypted recipient entry.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            key_id = uuid.UUID(str(entry.get('key_id')))
            nonce = base64.b64decode(entry.get('nonce'), validate=True)
            ciphertext = base64.b64decode(entry.get('ciphertext'), validate=True)
        except (ValueError, TypeError):
            return None, Response({'detail': 'Invalid encrypted recipient data.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(nonce) != 24 or len(ciphertext) < 16:
            return None, Response({'detail': 'Invalid encrypted recipient data.'}, status=status.HTTP_400_BAD_REQUEST)
        included_ids.add(key_id)

    if len(included_ids) != len(entries):
        return None, Response({'detail': 'Encrypted recipient keys must be unique.'}, status=status.HTTP_400_BAD_REQUEST)

    required_ids = set(
        SupportEncryptionKey.objects.filter(user_id=recipient_user_id).values_list('id', flat=True)
    )
    staff_ids = set(_support_staff_keys().values_list('id', flat=True))
    if not staff_ids:
        return None, Response({'detail': 'Support encryption keys are not configured yet.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    required_ids.update(staff_ids)
    required_ids.add(sender_key_id)
    if not required_ids or required_ids != included_ids:
        return None, Response({'detail': 'Encryption keys changed; refresh the recipient list and retry.'}, status=status.HTTP_409_CONFLICT)
    registered_ids = set(SupportEncryptionKey.objects.filter(id__in=included_ids).values_list('id', flat=True))
    if registered_ids != included_ids:
        return None, Response({'detail': 'One or more recipient keys are no longer registered.'}, status=status.HTTP_409_CONFLICT)

    serialized = json.dumps(envelope, separators=(',', ':'))
    if len(serialized.encode('utf-8')) > 64_000:
        return None, Response({'detail': 'Encrypted message is too large.'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    return serialized, None


class IsSupportStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_staff
            and (user.is_superuser or not user.assigned_pages or 'Support' in user.assigned_pages)
        )


class SupportChatView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        conversation = SupportConversation.objects.filter(user=request.user).first()
        if not conversation:
            return Response({
                'conversation_id': None,
                'messages': [],
                'unread_count': 0,
                'staff_typing': False,
                'is_closed': False,
                'support_presence': 'waiting',
            })

        if request.query_params.get('mark_read') == 'true':
            conversation.messages.filter(sender__is_staff=True, is_read=False).update(is_read=True)

        messages = conversation.messages.select_related('sender').all()
        unread_count = conversation.messages.filter(sender__is_staff=True, is_read=False).count()
        return Response({
            'conversation_id': conversation.id,
            'messages': [_support_message_data(message) for message in messages],
            'unread_count': unread_count,
            'staff_typing': _is_typing(conversation.staff_typing_at),
            'is_closed': conversation.is_closed,
            'support_presence': _support_presence_status(conversation),
        })

    def patch(self, request):
        is_typing = request.data.get('is_typing')
        if not isinstance(is_typing, bool):
            return Response({'is_typing': 'This field must be a boolean.'}, status=status.HTTP_400_BAD_REQUEST)
        conversation = SupportConversation.objects.filter(user=request.user).first()
        if conversation and not conversation.is_closed:
            conversation.customer_typing_at = timezone.now() if is_typing else None
            conversation.save(update_fields=['customer_typing_at'])
        return Response({'is_typing': is_typing})

    def post(self, request):
        if request.data.get('start') is True or request.data.get('reopen') is True:
            if not SupportEncryptionKey.objects.filter(user=request.user).exists():
                return Response(
                    {'detail': 'Register this device encryption key before starting support chat.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            conversation, created = SupportConversation.objects.get_or_create(user=request.user)
            if request.data.get('reopen') is True and conversation.is_closed:
                conversation.is_closed = False
                conversation.save(update_fields=['is_closed', 'updated_at'])
            return Response(
                {'conversation_id': conversation.id, 'is_closed': conversation.is_closed},
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )

        conversation, _ = SupportConversation.objects.get_or_create(user=request.user)
        body, error = _validate_support_ciphertext(request, request.user.id)
        if error:
            return error

        with transaction.atomic():
            conversation = SupportConversation.objects.select_for_update().get(pk=conversation.pk)
            if conversation.is_closed:
                return Response(
                    {'detail': 'This support conversation is closed. Reopen it before sending another message.'},
                    status=status.HTTP_409_CONFLICT,
                )
            should_send_admin_alert = not request.user.is_staff and not conversation.admin_new_message_alert_sent
            if should_send_admin_alert:
                conversation.admin_new_message_alert_sent = True
            message = SupportMessage.objects.create(conversation=conversation, sender=request.user, body=body)
            conversation.customer_typing_at = None
            update_fields = ['updated_at', 'customer_typing_at']
            if should_send_admin_alert:
                update_fields.append('admin_new_message_alert_sent')
            conversation.save(update_fields=update_fields)

        if should_send_admin_alert:
            try:
                send_admin_new_support_message_email(request.user.name, request.user.email)
            except Exception as error:
                logger.warning(
                    'Unable to send new support message alert for conversation %s (%s)',
                    conversation.id,
                    type(error).__name__,
                )
        return Response(_support_message_data(message), status=status.HTTP_201_CREATED)


class AdminSupportConversationListView(APIView):
    permission_classes = (IsSupportStaff,)

    def get(self, request):
        conversations = SupportConversation.objects.select_related('user').prefetch_related('messages__sender')
        results = []
        for conversation in conversations:
            latest = conversation.messages.order_by('-created_at').first()
            results.append({
                'id': conversation.id,
                'user_id': conversation.user_id,
                'user_name': conversation.user.name,
                'user_email': conversation.user.email,
                'updated_at': conversation.updated_at,
                'is_closed': conversation.is_closed,
                'unread_count': conversation.messages.filter(sender__is_staff=False, is_read=False).count(),
                'last_message': _support_message_data(latest) if latest else None,
            })
        return Response(results)


class AdminSupportConversationView(APIView):
    permission_classes = (IsSupportStaff,)

    def get_conversation(self, pk):
        try:
            return SupportConversation.objects.select_related('user').get(pk=pk)
        except SupportConversation.DoesNotExist:
            return None

    def get(self, request, pk):
        conversation = self.get_conversation(pk)
        if not conversation:
            return Response(status=status.HTTP_404_NOT_FOUND)
        _set_support_staff_presence(conversation, request.user, True)
        conversation.messages.filter(sender__is_staff=False, is_read=False).update(is_read=True)
        messages = conversation.messages.select_related('sender').all()
        return Response({
            'id': conversation.id,
            'user_id': conversation.user_id,
            'user_name': conversation.user.name,
            'user_email': conversation.user.email,
            'customer_typing': _is_typing(conversation.customer_typing_at),
            'is_closed': conversation.is_closed,
            'support_presence': _support_presence_status(conversation),
            'messages': [_support_message_data(message) for message in messages],
        })

    def patch(self, request, pk):
        conversation = self.get_conversation(pk)
        if not conversation:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if 'is_viewing' in request.data:
            is_viewing = request.data['is_viewing']
            if not isinstance(is_viewing, bool):
                return Response({'is_viewing': 'This field must be a boolean.'}, status=status.HTTP_400_BAD_REQUEST)
            _set_support_staff_presence(conversation, request.user, is_viewing)
            return Response({'is_viewing': is_viewing})

        if 'is_closed' in request.data:
            is_closed = request.data['is_closed']
            if not isinstance(is_closed, bool):
                return Response({'is_closed': 'This field must be a boolean.'}, status=status.HTTP_400_BAD_REQUEST)
            conversation.is_closed = is_closed
            if is_closed:
                conversation.customer_typing_at = None
                conversation.staff_typing_at = None
                conversation.save(update_fields=['is_closed', 'customer_typing_at', 'staff_typing_at', 'updated_at'])
            else:
                conversation.save(update_fields=['is_closed', 'updated_at'])
            return Response({'is_closed': conversation.is_closed})

        is_typing = request.data.get('is_typing')
        if not isinstance(is_typing, bool):
            return Response({'is_typing': 'This field must be a boolean.'}, status=status.HTTP_400_BAD_REQUEST)
        if conversation.is_closed and is_typing:
            return Response({'detail': 'This support conversation is closed.'}, status=status.HTTP_409_CONFLICT)
        conversation.staff_typing_at = timezone.now() if is_typing else None
        conversation.save(update_fields=['staff_typing_at'])
        return Response({'is_typing': is_typing})

    def post(self, request, pk):
        conversation = self.get_conversation(pk)
        if not conversation:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if conversation.is_closed:
            return Response(
                {'detail': 'This support conversation is closed. Reopen it before replying.'},
                status=status.HTTP_409_CONFLICT,
            )
        body, error = _validate_support_ciphertext(request, conversation.user_id)
        if error:
            return error

        message = SupportMessage.objects.create(conversation=conversation, sender=request.user, body=body)
        conversation.staff_typing_at = None
        conversation.save(update_fields=['updated_at', 'staff_typing_at'])
        return Response(_support_message_data(message), status=status.HTTP_201_CREATED)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = (permissions.AllowAny,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        try:
            send_welcome_email(user.name, user.email)
        except Exception:
            pass
        try:
            send_welcome_sms(user.name, user.phone)
        except Exception:
            pass
        Notification.objects.create(user=user, type='welcome', title='Welcome to Majo Gadgets!', body='Thanks for joining! Explore our latest gadgets and enjoy exclusive deals made just for you.')
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh)}, status=status.HTTP_201_CREATED)


class ForgotPasswordView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        user = User.objects.filter(email=email).first()
        # Always return 200 to avoid email enumeration
        if user:
            token = secrets.token_urlsafe(32)
            cache.set(f'pwd_reset:{token}', user.pk, timeout=3600)
            reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
            try:
                send_password_reset_email(user.name, user.email, reset_url)
            except Exception:
                pass
        return Response({'detail': 'If that email exists, a reset link has been sent.'})


class ResetPasswordView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        token = request.data.get('token', '')
        password = request.data.get('password', '')
        if not token or not password:
            return Response({'detail': 'Token and password are required.'}, status=status.HTTP_400_BAD_REQUEST)
        user_pk = cache.get(f'pwd_reset:{token}')
        if not user_pk:
            return Response({'detail': 'Invalid or expired reset link.'}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(pk=user_pk).first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(password)
        user.save()
        EmailMfaTrustedDevice.objects.filter(user=user).delete()
        EmailMfaChallenge.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=timezone.now())
        cache.delete(f'pwd_reset:{token}')
        try:
            send_password_changed_email(user.name, user.email)
        except Exception:
            pass
        Notification.objects.create(user=user, type='system', title='Password reset successfully', body='Your account password was reset. If you did not do this, please contact us immediately.')
        return Response({'detail': 'Password reset successful.'})


class ProfileView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        return self.request.user

    def patch(self, request, *args, **kwargs):
        serializer = UpdateProfileSerializer(
            request.user, data=request.data, partial=True, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if serializer.validated_data.get('new_password') or serializer.validated_data.get('password'):
            EmailMfaTrustedDevice.objects.filter(user=request.user).delete()
            try:
                send_password_changed_email(request.user.name, request.user.email)
            except Exception:
                pass
            Notification.objects.create(user=request.user, type='system', title='Password changed', body='Your account password was changed successfully. If you did not do this, please contact us immediately.')
        return Response(UserSerializer(request.user).data)

    def delete(self, request, *args, **kwargs):
        request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        items = CartItem.objects.filter(user=request.user)
        return Response(CartItemSerializer(items, many=True).data)

    def post(self, request):
        product_id = request.data.get('product_id')
        quantity = int(request.data.get('quantity', 1))
        item, created = CartItem.objects.get_or_create(
            user=request.user,
            product_id=product_id,
            defaults={
                'product_name': request.data.get('product_name', ''),
                'product_price': request.data.get('product_price', 0),
                'product_image': request.data.get('product_image'),
                'product_slug': request.data.get('product_slug', ''),
                'product_category': request.data.get('product_category', ''),
                'product_rating': request.data.get('product_rating', 0),
                'quantity': quantity,
            }
        )
        if not created:
            item.quantity += quantity
            item.save()
        return Response(CartItemSerializer(item).data, status=status.HTTP_201_CREATED)

    def delete(self, request):
        CartItem.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartItemView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def patch(self, request, product_id):
        try:
            item = CartItem.objects.get(user=request.user, product_id=product_id)
            quantity = int(request.data.get('quantity', item.quantity))
            if quantity <= 0:
                item.delete()
                return Response(status=status.HTTP_204_NO_CONTENT)
            item.quantity = quantity
            item.save()
            return Response(CartItemSerializer(item).data)
        except CartItem.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

    def delete(self, request, product_id):
        CartItem.objects.filter(user=request.user, product_id=product_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WishlistView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        items = WishlistItem.objects.filter(user=request.user)
        return Response(WishlistItemSerializer(items, many=True).data)

    def post(self, request):
        product_id = request.data.get('product_id')
        item, created = WishlistItem.objects.get_or_create(
            user=request.user,
            product_id=product_id,
            defaults={
                'product_name': request.data.get('product_name', ''),
                'product_price': request.data.get('product_price', 0),
                'product_image': request.data.get('product_image'),
                'product_slug': request.data.get('product_slug', ''),
                'product_category': request.data.get('product_category', ''),
                'product_rating': request.data.get('product_rating', 0),
            }
        )
        return Response(WishlistItemSerializer(item).data, status=status.HTTP_201_CREATED)


class WishlistItemView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def delete(self, request, product_id):
        WishlistItem.objects.filter(user=request.user, product_id=product_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        qs = Notification.objects.filter(user=request.user)
        return Response(NotificationSerializer(qs, many=True).data)

    def delete(self, request):
        """Delete all notifications for the user."""
        Notification.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def patch(self, request, pk):
        try:
            n = Notification.objects.get(pk=pk, user=request.user)
        except Notification.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        n.read = True
        n.save(update_fields=['read'])
        return Response(NotificationSerializer(n).data)

    def delete(self, request, pk):
        Notification.objects.filter(pk=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationMarkAllReadView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        Notification.objects.filter(user=request.user, read=False).update(read=True)
        return Response({'status': 'ok'})


class GoogleLoginView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        credential = request.data.get('credential', '')
        if not credential:
            return Response({'detail': 'Google credential is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            import urllib.request, json as _json
            with urllib.request.urlopen(f'https://www.googleapis.com/oauth2/v3/userinfo?access_token={credential}') as r:
                info = _json.loads(r.read())
        except Exception:
            return Response({'detail': 'Invalid Google token.'}, status=status.HTTP_401_UNAUTHORIZED)

        email = info.get('email', '').lower()
        name = info.get('name', '') or email.split('@')[0]
        if not email:
            return Response({'detail': 'Could not get email from Google.'}, status=status.HTTP_400_BAD_REQUEST)

        user, created = User.objects.get_or_create(email=email, defaults={'name': name})
        if not user.is_active:
            return Response({'detail': 'No active account found with the given credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
        _store_google_avatar(user, info.get('picture'))
        if created:
            user.set_unusable_password()
            user.save()
            try:
                send_welcome_email(user.name, user.email)
            except Exception:
                pass
            try:
                send_welcome_sms(user.name, user.phone)
            except Exception:
                pass
            Notification.objects.create(user=user, type='welcome', title='Welcome to Majo Gadgets!', body='Thanks for joining! Explore our latest gadgets and enjoy exclusive deals made just for you.')

        if not user.phone or not user.district:
            # Issue a short-lived JWT encoding just the user pk — no server-side storage needed
            from rest_framework_simplejwt.tokens import AccessToken
            from datetime import timedelta
            token = AccessToken()
            token.set_exp(lifetime=timedelta(minutes=10))
            token['user_id'] = user.pk
            token['profile_setup'] = True
            return Response({'needs_profile': True, 'tmp_token': str(token), 'name': user.name, 'email': user.email})

        return _verified_login_response(user, request)


class CompleteGoogleProfileView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        tmp = request.data.get('tmp_token', '')
        if not tmp:
            return Response({'detail': 'Invalid session.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            token = AccessToken(tmp)
            if not token.get('profile_setup'):
                raise Exception('not a profile setup token')
            user_pk = token['user_id']
        except Exception:
            return Response({'detail': 'Session expired. Please sign in again.'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(pk=user_pk).first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_400_BAD_REQUEST)

        phone = request.data.get('phone', '').strip()
        region = request.data.get('region', '').strip()
        district = request.data.get('district', '').strip()
        village = request.data.get('village', '').strip()

        if not phone or not region or not district:
            return Response({'detail': 'Phone, region and district are required.'}, status=status.HTTP_400_BAD_REQUEST)

        user.phone = phone
        user.region = region
        user.district = district
        user.village = village
        user.country = 'Uganda'
        user.save()

        return _verified_login_response(user, request)


# ── Behaviour tracking ────────────────────────────────────────────────────────

SCORE_MAP = {'view': 1, 'click': 3, 'category': 5}
MAX_RECENT = 60


def _update_behaviour(user, event_type, category_slug, product_id=None):
    behaviour, _ = UserBehaviour.objects.get_or_create(user=user)
    scores = dict(behaviour.category_scores or {})
    recent = list(behaviour.recent_product_ids or [])
    if category_slug:
        scores[category_slug] = scores.get(category_slug, 0) + SCORE_MAP.get(event_type, 1)
    if product_id:
        recent = [product_id] + [pid for pid in recent if pid != product_id]
        recent = recent[:MAX_RECENT]
    behaviour.category_scores = scores
    behaviour.recent_product_ids = recent
    behaviour.save(update_fields=['category_scores', 'recent_product_ids', 'updated_at'])


class BehaviourTrackView(APIView):
    """
    POST /api/auth/behaviour/
    { event: 'view'|'click'|'category', category_slug: str, product_id?: int }
    """
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        event = request.data.get('event', '')
        category_slug = request.data.get('category_slug', '').strip()
        if event not in SCORE_MAP or not category_slug:
            return Response({'detail': 'Invalid payload.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            product_id = int(request.data['product_id']) if request.data.get('product_id') else None
        except (ValueError, TypeError):
            product_id = None
        _update_behaviour(request.user, event, category_slug, product_id)
        return Response({'status': 'ok'})


class RecommendedProductsView(APIView):
    """
    GET /api/auth/recommended/?page=1&page_size=12&exclude=1,2,3
    Returns products ranked by the authenticated user's behaviour scores.
    Falls back to random order for guests.
    """
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        import random
        from products.models import Product
        from products.serializers import ProductSerializer

        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(24, int(request.query_params.get('page_size', 12)))
        exclude_ids = set()
        for x in request.query_params.get('exclude', '').split(','):
            try:
                exclude_ids.add(int(x.strip()))
            except ValueError:
                pass

        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('images')
        if exclude_ids:
            qs = qs.exclude(id__in=exclude_ids)

        products = list(qs)
        total = len(products)

        if request.user and request.user.is_authenticated:
            behaviour = getattr(request.user, 'behaviour', None)
            scores = dict(behaviour.category_scores) if behaviour else {}
            recent_ids = set(behaviour.recent_product_ids) if behaviour else set()

            def rank(p):
                cat_slug = p.category.slug if p.category else ''
                return scores.get(cat_slug, 0) + (-20 if p.id in recent_ids else 0) + random.uniform(0, 3)

            products.sort(key=rank, reverse=True)
        else:
            random.shuffle(products)

        start = (page - 1) * page_size
        page_products = products[start:start + page_size]
        has_next = (start + page_size) < total

        return Response({
            'results': ProductSerializer(page_products, many=True).data,
            'count': total,
            'next': page + 1 if has_next else None,
        })


# ── Behaviour tracking ────────────────────────────────────────────────────────

SCORE_MAP = {'view': 1, 'click': 3, 'category': 5}
MAX_RECENT = 60


def _update_behaviour(user, event_type, category_slug, product_id=None):
    behaviour, _ = UserBehaviour.objects.get_or_create(user=user)
    scores = dict(behaviour.category_scores or {})
    recent = list(behaviour.recent_product_ids or [])
    if category_slug:
        scores[category_slug] = scores.get(category_slug, 0) + SCORE_MAP.get(event_type, 1)
    if product_id:
        recent = [product_id] + [pid for pid in recent if pid != product_id]
        recent = recent[:MAX_RECENT]
    behaviour.category_scores = scores
    behaviour.recent_product_ids = recent
    behaviour.save(update_fields=['category_scores', 'recent_product_ids', 'updated_at'])


class BehaviourTrackView(APIView):
    """
    POST /api/auth/behaviour/
    { event: 'view'|'click'|'category', category_slug: str, product_id?: int }
    """
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        event = request.data.get('event', '')
        category_slug = request.data.get('category_slug', '').strip()
        if event not in SCORE_MAP or not category_slug:
            return Response({'detail': 'Invalid payload.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            product_id = int(request.data['product_id']) if request.data.get('product_id') else None
        except (ValueError, TypeError):
            product_id = None
        _update_behaviour(request.user, event, category_slug, product_id)
        return Response({'status': 'ok'})


class RecommendedProductsView(APIView):
    """
    GET /api/auth/recommended/?page=1&page_size=12&exclude=1,2,3
    Returns products ranked by the authenticated user's behaviour scores.
    Falls back to random order for guests.
    """
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        import random
        from products.models import Product
        from products.serializers import ProductSerializer

        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(24, int(request.query_params.get('page_size', 12)))
        exclude_ids = set()
        for x in request.query_params.get('exclude', '').split(','):
            try:
                exclude_ids.add(int(x.strip()))
            except ValueError:
                pass

        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('images')
        if exclude_ids:
            qs = qs.exclude(id__in=exclude_ids)

        products = list(qs)
        total = len(products)

        if request.user and request.user.is_authenticated:
            behaviour = getattr(request.user, 'behaviour', None)
            scores = dict(behaviour.category_scores) if behaviour else {}
            recent_ids = set(behaviour.recent_product_ids) if behaviour else set()

            def rank(p):
                cat_slug = p.category.slug if p.category else ''
                return scores.get(cat_slug, 0) + (-20 if p.id in recent_ids else 0) + random.uniform(0, 3)

            products.sort(key=rank, reverse=True)
        else:
            random.shuffle(products)

        start = (page - 1) * page_size
        page_products = products[start:start + page_size]
        has_next = (start + page_size) < total

        return Response({
            'results': ProductSerializer(page_products, many=True).data,
            'count': total,
            'next': page + 1 if has_next else None,
        })
