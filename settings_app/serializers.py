from rest_framework import serializers
from .models import PlatformSettings, DeliverySettings, District, CookiePolicy, CookieConsent


class PlatformSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSettings
        fields = (
            'ui_active', 'allow_selling',
            'initial_charge', 'commission',
            'withdrawal_minimum', 'withdrawal_fee',
            'vat', 'free_delivery_threshold',
        )


class DeliverySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliverySettings
        fields = ('global_fee',)


class DistrictSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        fields = ('id', 'name', 'price', 'region')


class CookiePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = CookiePolicy
        fields = ('content', 'updated_at')
        read_only_fields = ('updated_at',)


class CookieConsentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CookieConsent
        fields = ('necessary', 'analytics', 'marketing', 'updated_at')
        read_only_fields = ('updated_at',)
