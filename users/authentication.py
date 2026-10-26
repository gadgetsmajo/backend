from django.db import models
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken


def requires_email_mfa(user):
    if user.is_staff:
        return True

    from traders.models import TraderApplication

    return TraderApplication.objects.filter(status='approved').filter(
        models.Q(user=user) | models.Q(email__iexact=user.email)
    ).exists()


class MfaJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if requires_email_mfa(user) and token.get('email_mfa_verified') is not True:
            raise AuthenticationFailed('Email verification is required. Sign in again to receive a code.')
        return user, token


class MfaTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        refresh = RefreshToken(attrs['refresh'])
        user_id = refresh.get(api_settings.USER_ID_CLAIM)
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
        if user is None:
            raise AuthenticationFailed('User not found.')
        if requires_email_mfa(user) and refresh.get('email_mfa_verified') is not True:
            raise AuthenticationFailed('Email verification is required. Sign in again to receive a code.')
        return data
