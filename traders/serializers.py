import os
import re

from rest_framework import serializers
from django.core.exceptions import ObjectDoesNotExist
from .models import TraderApplication, TraderProduct, TraderSale, TraderExpense, TraderOrderItem, TraderInventoryItem, TraderStockMovement


MAX_TRADER_DOCUMENT_SIZE = 10 * 1024 * 1024
ALLOWED_TRADER_DOCUMENT_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf'}


def _validate_trader_document(upload, label):
    extension = os.path.splitext(upload.name)[1].lower()
    if extension not in ALLOWED_TRADER_DOCUMENT_EXTENSIONS:
        raise serializers.ValidationError(f'{label} must be a JPG, PNG, or PDF file.')
    if upload.size > MAX_TRADER_DOCUMENT_SIZE:
        raise serializers.ValidationError(f'{label} must be 10 MB or smaller.')
    return upload


class TraderApplicationSerializer(serializers.ModelSerializer):
    agreed_to_terms = serializers.BooleanField(required=True)
    national_id_document = serializers.FileField(write_only=True, required=True)
    ura_certificate_document = serializers.FileField(write_only=True, required=False, allow_null=True)
    business_location_proof = serializers.FileField(write_only=True, required=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.name', read_only=True, default=None)

    class Meta:
        model = TraderApplication
        fields = '__all__'
        read_only_fields = (
            'id', 'uuid', 'status', 'admin_note', 'reviewed_by', 'reviewed_by_name', 'reviewed_at',
            'terms_accepted_at', 'documents_verified', 'agreement_reference', 'agreement_issued_at',
            'user', 'created_at', 'updated_at',
        )

    def validate_email(self, value):
        # Allow re-application if existing record is rejected
        qs = TraderApplication.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.filter(status__in=('pending', 'approved')).exists():
            raise serializers.ValidationError('An active application with this email already exists.')
        # Delete old rejected record so new one can be created cleanly
        qs.filter(status='rejected').delete()
        return value

    def validate_national_id(self, value):
        normalized = re.sub(r'[\s-]', '', value).upper()
        if (
            not 8 <= len(normalized) <= 20
            or not normalized.isalnum()
            or not any(character.isalpha() for character in normalized)
            or not any(character.isdigit() for character in normalized)
        ):
            raise serializers.ValidationError('Enter the National ID exactly as printed on the uploaded ID copy.')
        return normalized

    def validate_national_id_document(self, value):
        return _validate_trader_document(value, 'National ID copy')

    def validate_ura_certificate_document(self, value):
        return _validate_trader_document(value, 'URA certificate')

    def validate_business_location_proof(self, value):
        return _validate_trader_document(value, 'Business location proof')

    def validate(self, attrs):
        tin = attrs.get('tin', getattr(self.instance, 'tin', '')).strip()
        ura_certificate = attrs.get('ura_certificate_document') or getattr(self.instance, 'ura_certificate_document', None)
        if not tin and not ura_certificate:
            raise serializers.ValidationError({'tin': 'Enter a URA TIN or upload a URA certificate.'})
        return attrs

    def validate_agreed_to_terms(self, value):
        if not value:
            raise serializers.ValidationError('You must read and accept the trader rules and terms before applying.')
        return value


class TraderApplicationAdminSerializer(serializers.ModelSerializer):
    reviewed_by_name = serializers.CharField(source='reviewed_by.name', read_only=True, default=None)
    user_email = serializers.CharField(source='user.email', read_only=True, default=None)
    logo_url = serializers.SerializerMethodField()
    has_national_id_document = serializers.SerializerMethodField()
    has_ura_certificate_document = serializers.SerializerMethodField()
    has_business_location_proof = serializers.SerializerMethodField()
    has_agreement_signature_image = serializers.SerializerMethodField()

    class Meta:
        model = TraderApplication
        fields = (
            'id', 'uuid', 'full_name', 'email', 'phone', 'national_id', 'has_national_id_document',
            'business_name', 'business_type', 'business_reg_no', 'tin', 'has_ura_certificate_document',
            'location', 'has_business_location_proof', 'district', 'website', 'product_categories',
            'monthly_volume', 'experience', 'logo', 'logo_url', 'bio', 'is_visible', 'is_closed',
            'agreed_to_terms', 'terms_accepted_at', 'documents_verified', 'agreement_reference',
            'agreement_issued_at', 'agreement_version', 'agreement_required', 'agreement_signed_name',
            'agreement_signed_at', 'has_agreement_signature_image', 'status', 'admin_note', 'reviewed_by', 'reviewed_by_name',
            'reviewed_at', 'user', 'user_email', 'created_at', 'updated_at',
        )

    def get_has_national_id_document(self, obj):
        return bool(obj.national_id_document)

    def get_has_ura_certificate_document(self, obj):
        return bool(obj.ura_certificate_document)

    def get_has_business_location_proof(self, obj):
        return bool(obj.business_location_proof)

    def get_has_agreement_signature_image(self, obj):
        return bool(obj.agreement_signature_image)

    def get_logo_url(self, obj):
        if obj.logo:
            return obj.logo.url
        return None


class TraderAgreementSignatureSerializer(serializers.Serializer):
    accepted = serializers.BooleanField(required=True)
    signed_name = serializers.CharField(max_length=150, trim_whitespace=True)
    signature_image = serializers.ImageField(required=False, allow_null=True)

    def validate_accepted(self, value):
        if not value:
            raise serializers.ValidationError('Accept the agreement before signing.')
        return value

    def validate_signature_image(self, value):
        if value and value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError('Signature image must be 5 MB or smaller.')
        return value


class TraderProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    public_product_id = serializers.SerializerMethodField()
    category_id = serializers.IntegerField(source='category.id', read_only=True, allow_null=True, default=None)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = TraderProduct
        fields = (
            'id', 'uuid', 'name', 'short_description', 'long_description', 'description',
            'price', 'original_price', 'delivery_fee', 'stock',
            'category_id', 'category_name', 'public_product_id',
            'image_url', 'is_active', 'is_featured', 'is_new_deal',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'uuid', 'image_url', 'category_id', 'category_name', 'created_at', 'updated_at')

    def get_image_url(self, obj):
        if obj.image:
            return obj.image.url
        return obj.image_url or None

    def get_public_product_id(self, obj):
        try:
            return obj.public_product.pk
        except ObjectDoesNotExist:
            return None


class TraderSaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraderSale
        fields = ('id', 'uuid', 'product', 'product_name', 'quantity', 'unit_price', 'total', 'customer_name', 'note', 'created_at')
        read_only_fields = ('id', 'uuid', 'created_at')


class TraderExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraderExpense
        fields = ('id', 'uuid', 'description', 'amount', 'date', 'note', 'created_at')
        read_only_fields = ('id', 'uuid', 'created_at')


class TraderInventoryItemSerializer(serializers.ModelSerializer):
    product_name  = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()
    product_price = serializers.DecimalField(source='product.price', max_digits=12, decimal_places=2, read_only=True)
    product_stock = serializers.IntegerField(source='product.stock', read_only=True)
    product_uuid  = serializers.CharField(source='product.uuid', read_only=True)

    class Meta:
        model = TraderInventoryItem
        fields = ('id', 'product', 'product_uuid', 'product_name', 'product_image', 'product_price',
                  'product_stock', 'quantity', 'cost_price', 'location', 'note', 'updated_at', 'created_at')
        read_only_fields = ('id', 'product_uuid', 'product_name', 'product_image', 'product_price',
                            'product_stock', 'updated_at', 'created_at')

    def get_product_image(self, obj):
        try:
            return obj.product.image.url
        except Exception:
            return obj.product.image_url or None


class TraderStockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='item.product.name', read_only=True)

    class Meta:
        model = TraderStockMovement
        fields = ('id', 'item', 'product_name', 'type', 'quantity', 'note', 'created_at')
        read_only_fields = ('id', 'product_name', 'created_at')


class TraderOrderItemSerializer(serializers.ModelSerializer):
    order_code        = serializers.CharField(source='order_item.order.code', read_only=True)
    order_id          = serializers.IntegerField(source='order_item.order.id', read_only=True)
    order_status      = serializers.CharField(source='order_item.order.status', read_only=True)
    order_created_at  = serializers.DateTimeField(source='order_item.order.created_at', read_only=True)
    delivery_address  = serializers.CharField(source='order_item.order.delivery_address', read_only=True)
    product_name      = serializers.CharField(source='order_item.product.name', read_only=True)
    product_image     = serializers.SerializerMethodField()
    quantity          = serializers.IntegerField(source='order_item.quantity', read_only=True)
    price             = serializers.DecimalField(source='order_item.price', max_digits=10, decimal_places=2, read_only=True)
    order_item_id     = serializers.IntegerField(source='order_item.id', read_only=True)
    status_changed_by_name = serializers.CharField(source='status_changed_by.name', read_only=True, default=None)
    ready_at          = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TraderOrderItem
        fields = (
            'id', 'order_item_id', 'order_code', 'order_id', 'order_status',
            'order_created_at', 'delivery_address',
            'product_name', 'product_image', 'quantity', 'price',
            'status', 'note', 'status_changed_by_name', 'ready_at', 'updated_at',
        )
        read_only_fields = ('id', 'order_item_id', 'order_code', 'order_id', 'order_status',
                            'order_created_at', 'delivery_address',
                            'product_name', 'product_image', 'quantity', 'price',
                            'status_changed_by_name', 'updated_at')

    def get_product_image(self, obj):
        try:
            return obj.order_item.product.image.url
        except Exception:
            return None
