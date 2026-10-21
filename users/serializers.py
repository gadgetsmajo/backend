import re

from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User


def normalize_phone_number(value):
    if not value:
        return ''

    digits = re.sub(r'\D', '', value)
    if not digits:
        return ''

    if digits.startswith('0') and len(digits) == 10:
        return '256' + digits[1:]
    if digits.startswith('256') and len(digits) == 12:
        return digits
    return digits


class SignupSerializer(serializers.Serializer):
    full_name        = serializers.CharField(max_length=150)
    email            = serializers.EmailField(required=False, allow_blank=True)
    phone_number     = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password         = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email        = attrs.get('email', '').strip()
        phone_number = attrs.get('phone_number', '').strip()

        if not email and not phone_number:
            raise serializers.ValidationError({'identifier': 'Email or phone number is required.'})

        if attrs['password'] != attrs.pop('confirm_password'):
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})

        if email:
            if User.objects.filter(email=email).exists():
                raise serializers.ValidationError({'email': 'An account with this email already exists.'})
            attrs['email'] = email
        else:
            attrs['email'] = ''

        if phone_number:
            if User.objects.filter(phone_number=phone_number).exists():
                raise serializers.ValidationError({'phone_number': 'An account with this phone number already exists.'})
            attrs['phone_number'] = phone_number
        else:
            attrs['phone_number'] = ''

        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    email        = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    password     = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email        = attrs.get('email', '').strip()
        phone_number = attrs.get('phone_number', '').strip()
        password     = attrs.get('password')

        user = None
        if email:
            user = authenticate(username=email, password=password)
        elif phone_number:
            normalized_phone = normalize_phone_number(phone_number)
            candidates = {phone_number, normalized_phone}
            if normalized_phone.startswith('256'):
                candidates.add('0' + normalized_phone[3:])
                candidates.add('+' + normalized_phone)
            for candidate in candidates:
                if not candidate:
                    continue
                try:
                    u = User.objects.get(phone_number__iexact=candidate)
                    if u.check_password(password):
                        user = u
                        break
                except User.DoesNotExist:
                    continue

        if not user:
            raise serializers.ValidationError({'detail': 'Invalid credentials.'})
        if not user.is_active:
            raise serializers.ValidationError({'detail': 'Account is disabled.'})
        attrs['user'] = user
        return attrs
