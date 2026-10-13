import logging
import secrets
from urllib.parse import urlparse
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model, authenticate
from django.core.cache import cache
from django.conf import settings
from .serializers import RegisterSerializer, UserSerializer, UpdateProfileSerializer, CartItemSerializer, WishlistItemSerializer, NotificationSerializer
from .models import CartItem, WishlistItem, Notification, UserBehaviour
from .emails import send_welcome_email, send_password_reset_email, send_password_changed_email
from .sms import send_welcome_sms

User = get_user_model()
logger = logging.getLogger(__name__)


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
        refresh = RefreshToken.for_user(user)
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh)})


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

        refresh = RefreshToken.for_user(user)
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh)})


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

        refresh = RefreshToken.for_user(user)
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh)})


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
