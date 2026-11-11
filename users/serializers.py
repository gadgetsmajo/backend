from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import CartItem, WishlistItem, Notification
from products.models import Product, ProductVariant
from settings_app.pricing import price_with_platform_charges

User = get_user_model()


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ('id', 'type', 'title', 'body', 'action_url', 'read', 'created_at')
        read_only_fields = ('id', 'type', 'title', 'body', 'created_at')


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ('email', 'name', 'phone', 'password', 'country', 'region', 'district', 'village')

    def create(self, validated_data):
        validated_data.pop('is_staff', None)
        validated_data.pop('is_superuser', None)
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()

    def get_avatar(self, obj):
        if not obj.avatar:
            return None
        return obj.avatar.url

    class Meta:
        model = User
        fields = ('id', 'email', 'name', 'phone', 'avatar', 'is_staff', 'is_superuser', 'assigned_pages', 'created_at', 'country', 'region', 'district', 'village')
        read_only_fields = ('id', 'email', 'is_superuser', 'created_at')


class UpdateProfileSerializer(serializers.ModelSerializer):
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password = serializers.CharField(write_only=True, required=False, min_length=8, allow_blank=True)
    password_confirm = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8, required=False, allow_blank=True)
    is_staff = serializers.BooleanField(required=False)

    class Meta:
        model = User
        fields = ('name', 'email', 'phone', 'avatar', 'current_password', 'new_password', 'password_confirm', 'password', 'is_staff', 'assigned_pages')

    def validate(self, attrs):
        current_password = attrs.get('current_password')
        new_password = attrs.get('new_password') or attrs.get('password')
        password_confirm = attrs.get('password_confirm')

        has_password_change = any(value not in (None, '') for value in [current_password, new_password, password_confirm])
        if not has_password_change:
            return attrs

        if not current_password:
            raise serializers.ValidationError({'current_password': 'Current password is required.'})
        if not self.instance.check_password(current_password):
            raise serializers.ValidationError({'current_password': 'Current password is incorrect.'})
        if not new_password:
            raise serializers.ValidationError({'new_password': 'New password is required.'})
        if not password_confirm:
            raise serializers.ValidationError({'password_confirm': 'Please confirm your new password.'})
        if new_password != password_confirm:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})

        return attrs

    def update(self, instance, validated_data):
        new_password = validated_data.pop('new_password', None)
        if new_password is None:
            new_password = validated_data.pop('password', None)
        validated_data.pop('current_password', None)
        validated_data.pop('password_confirm', None)

        request = self.context.get('request')
        if not (request and request.user.is_staff):
            validated_data.pop('is_staff', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if new_password:
            instance.set_password(new_password)
        instance.save()
        return instance


class CartItemSerializer(serializers.ModelSerializer):
    product_price = serializers.SerializerMethodField()
    variant_id = serializers.IntegerField(read_only=True)
    variant_options = serializers.SerializerMethodField()
    variant_sku = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = (
            'id', 'product_id', 'variant_id', 'variant_options', 'variant_sku',
            'product_name', 'product_price', 'product_image', 'product_slug',
            'product_category', 'product_rating', 'quantity', 'added_at',
        )
        read_only_fields = ('id', 'added_at')

    def get_product_price(self, obj):
        price = obj.variant.price if obj.variant_id else Product.objects.filter(
            pk=obj.product_id,
        ).values_list('price', flat=True).first()
        if price is None:
            price = obj.product_price
        return str(price_with_platform_charges(price))

    def get_variant_options(self, obj):
        return obj.variant.options if obj.variant_id else obj.variant_options

    def get_variant_sku(self, obj):
        return obj.variant.sku if obj.variant_id else ''


class WishlistItemSerializer(serializers.ModelSerializer):
    product_price = serializers.SerializerMethodField()

    class Meta:
        model = WishlistItem
        fields = ('id', 'product_id', 'product_name', 'product_price', 'product_image', 'product_slug', 'product_category', 'product_rating', 'added_at')
        read_only_fields = ('id', 'added_at')

    def get_product_price(self, obj):
        price = Product.objects.filter(pk=obj.product_id).values_list('price', flat=True).first()
        if price is None:
            price = obj.product_price
        return str(price_with_platform_charges(price))
