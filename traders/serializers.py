import json
import os
import re

from rest_framework import serializers
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Exists, OuterRef, Sum
from products.models import CatalogProduct, Category, ProductVariant
from products.serializers import (
    ProductVariantSerializer, TruncatedCharField, to_plain_data, validate_variant_removals,
)
from .models import (
    TraderApplication, TraderProduct, TraderSale, TraderExpense, TraderOrderItem,
    TraderInventoryItem, TraderStockMovement, TraderEarning, TraderWithdrawal,
)


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
            'payout_method', 'payout_provider', 'payout_account_name', 'payout_account_number', 'payout_branch',
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


class TraderPayoutAccountSerializer(serializers.Serializer):
    payout_method = serializers.ChoiceField(
        choices=TraderApplication.PAYOUT_METHODS,
        allow_blank=True,
    )
    payout_provider = serializers.CharField(max_length=100, allow_blank=True, required=False)
    payout_account_name = serializers.CharField(max_length=150, allow_blank=True, required=False)
    payout_account_number = serializers.CharField(max_length=50, allow_blank=True, required=False)
    payout_branch = serializers.CharField(max_length=150, allow_blank=True, required=False)

    def validate(self, attrs):
        if not attrs['payout_method']:
            return attrs
        for field in ('payout_provider', 'payout_account_name', 'payout_account_number'):
            if not attrs.get(field, '').strip():
                raise serializers.ValidationError({field: 'This field is required for payouts.'})
        return attrs


class TraderProductSerializer(serializers.ModelSerializer):
    name = serializers.CharField(required=False, max_length=255)
    short_description = TruncatedCharField(max_length=300, required=False, allow_blank=True)
    image_url = serializers.SerializerMethodField()
    public_product_id = serializers.SerializerMethodField()
    catalog_product_id = serializers.PrimaryKeyRelatedField(
        source='catalog_product',
        queryset=CatalogProduct.objects.filter(review_status='approved', is_active=True),
        required=False,
        allow_null=True,
        write_only=True,
    )
    catalog_product = serializers.SerializerMethodField()
    catalog_image_references = serializers.ListField(
        child=serializers.CharField(max_length=500), required=False,
    )
    review_status = serializers.SerializerMethodField()
    review_note = serializers.SerializerMethodField()
    variant_list = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, required=False, write_only=True)
    submit_for_review = serializers.BooleanField(required=False, default=True, write_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source='category', queryset=Category.objects.all(), required=False, allow_null=True,
    )
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = TraderProduct
        fields = (
            'id', 'uuid', 'name', 'short_description', 'long_description', 'description',
            'brand', 'condition', 'tags', 'specifications',
            'price', 'original_price', 'delivery_fee', 'stock', 'trader_sku',
            'availability', 'warranty', 'delivery_options', 'package_details',
            'category_id', 'category_name', 'public_product_id', 'catalog_product_id',
            'catalog_product', 'catalog_image_references',
            'image_url', 'is_active', 'is_featured', 'is_new_deal',
            'review_status', 'review_note', 'variants', 'variant_list', 'submit_for_review',
            'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'uuid', 'image_url', 'category_name', 'created_at', 'updated_at',
            'review_status', 'review_note', 'variant_list',
        )

    def to_internal_value(self, data):
        data = to_plain_data(data)
        for field in ('tags', 'specifications', 'variants', 'catalog_image_references'):
            value = data.get(field)
            if isinstance(value, str):
                try:
                    data[field] = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise serializers.ValidationError({field: 'Enter valid JSON.'}) from exc
        if isinstance(data.get('delivery_options'), str):
            try:
                data['delivery_options'] = json.loads(data['delivery_options'])
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError({'delivery_options': 'Enter valid JSON.'}) from exc
        if isinstance(data.get('variants'), list):
            request = self.context.get('request')
            files = request.FILES if request else {}
            for index, variant in enumerate(data['variants']):
                image = files.get(f'variant_image_{index}')
                if image and isinstance(variant, dict):
                    variant['image'] = image
        empty_fields = ('category_id', 'original_price')
        if any(data.get(field) == '' for field in empty_fields):
            for field in empty_fields:
                if data.get(field) == '':
                    data[field] = None
        return super().to_internal_value(data)

    def create(self, validated_data):
        variants = validated_data.pop('variants', None)
        submit_for_review = validated_data.pop('submit_for_review', True)
        catalog_product = validated_data.get('catalog_product')
        if catalog_product:
            self._inherit_catalog_fields(validated_data, catalog_product)
        product = super().create(validated_data)
        product._submitted_variants = variants
        product._submit_for_review = submit_for_review
        return product

    def update(self, instance, validated_data):
        variants = validated_data.pop('variants', None)
        submit_for_review = validated_data.pop('submit_for_review', None)
        catalog_product = validated_data.get('catalog_product', instance.catalog_product)
        if instance.catalog_product_id and catalog_product != instance.catalog_product:
            raise serializers.ValidationError({
                'catalog_product_id': 'An attached catalog product cannot be replaced or removed.',
            })
        if catalog_product:
            self._inherit_catalog_fields(validated_data, catalog_product, instance=instance)
        product = super().update(instance, validated_data)
        product._submitted_variants = variants
        product._submit_for_review = submit_for_review
        return product

    def validate(self, attrs):
        catalog_product = attrs.get(
            'catalog_product',
            self.instance.catalog_product if self.instance else None,
        )
        if self.instance and self.instance.catalog_product_id and (
            'catalog_product' in attrs and attrs['catalog_product'] != self.instance.catalog_product
        ):
            raise serializers.ValidationError({
                'catalog_product_id': 'An attached catalog product cannot be replaced or removed.',
            })
        if catalog_product:
            if catalog_product.review_status != 'approved' or not catalog_product.is_active:
                raise serializers.ValidationError({'catalog_product_id': 'This catalog product is unavailable.'})
            field_map = {
                'name': catalog_product.name,
                'brand': catalog_product.brand,
                'category': catalog_product.category,
                'tags': catalog_product.tags,
                'specifications': catalog_product.specifications,
                'short_description': catalog_product.short_description,
                'long_description': catalog_product.long_description,
                'description': catalog_product.long_description,
            }
            for field, catalog_value in field_map.items():
                if field in attrs and attrs[field] != catalog_value:
                    input_name = 'category_id' if field == 'category' else field
                    raise serializers.ValidationError({
                        input_name: 'This information is managed in the shared catalog.',
                    })
            if 'catalog_image_references' in attrs:
                allowed_references = set(catalog_product.image_references or [])
                if not set(attrs['catalog_image_references']).issubset(allowed_references):
                    raise serializers.ValidationError({
                        'catalog_image_references': 'Select images already approved for this catalog product.',
                    })
            self._inherit_catalog_fields(attrs, catalog_product, instance=self.instance)
        elif not (self.instance and self.instance.name) and not attrs.get('name', '').strip():
            raise serializers.ValidationError({'name': 'Name is required.'})

        category = attrs.get('category', getattr(self.instance, 'category', None))
        specifications = attrs.get('specifications', getattr(self.instance, 'specifications', {}))
        variants = attrs.get('variants')
        public_product = None
        if self.instance:
            try:
                public_product = self.instance.public_product
            except ObjectDoesNotExist:
                pass
        if not isinstance(specifications, dict):
            raise serializers.ValidationError({'specifications': 'Specifications must be an object.'})
        tags = attrs.get('tags', getattr(self.instance, 'tags', []))
        if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise serializers.ValidationError({'tags': 'Tags must be a list of non-empty strings.'})
        delivery_options = attrs.get('delivery_options', getattr(self.instance, 'delivery_options', []))
        if not isinstance(delivery_options, list) or any(
            not isinstance(option, str) or not option.strip() for option in delivery_options
        ):
            raise serializers.ValidationError({'delivery_options': 'Delivery options must be a list of non-empty strings.'})
        if len(variants or []) > 100:
            raise serializers.ValidationError({'variants': 'A product cannot have more than 100 variants.'})
        if variants is not None:
            skus = [variant.get('sku', '').strip().casefold() for variant in variants if variant.get('sku', '').strip()]
            if len(skus) != len(set(skus)):
                raise serializers.ValidationError({'variants': 'Each variant SKU must be unique.'})
            option_sets = [
                tuple(sorted((key, str(value)) for key, value in variant.get('options', {}).items()))
                for variant in variants
            ]
            if len(option_sets) != len(set(option_sets)):
                raise serializers.ValidationError({'variants': 'Variant option combinations must be unique.'})
            validate_variant_removals(public_product, variants)
            if catalog_product:
                catalog_options = catalog_product.get_variant_options()
                if variants and not catalog_options:
                    raise serializers.ValidationError({
                        'variants': 'This catalog product has no approved variants. Ask an administrator to add them.',
                    })
                canonical_options = {
                    json.dumps(option, sort_keys=True, separators=(',', ':'))
                    for option in catalog_options
                    if isinstance(option, dict)
                }
                if any(
                    json.dumps(variant.get('options', {}), sort_keys=True, separators=(',', ':'))
                    not in canonical_options
                    for variant in variants
                ):
                    raise serializers.ValidationError({
                        'variants': 'Select only variants defined in the shared catalog.',
                    })
        if category:
            errors = {}
            validate_specifications = (
                self.instance is None or 'category' in attrs or 'specifications' in attrs
            )
            validate_variants = (
                self.instance is None
                or 'category' in attrs
                or (
                    variants is not None
                    and (bool(variants) or (public_product and public_product.variants.exists()))
                )
            )
            variant_data = variants
            if variant_data is None and self.instance and validate_variants:
                variant_data = [
                    {'options': variant.options}
                    for variant in public_product.variants.all()
                ] if public_product else []
            for attribute in category.attributes.filter(is_required=True):
                if attribute.is_variant:
                    if validate_variants and (
                        not variant_data
                        or any(attribute.key not in variant.get('options', {}) for variant in variant_data)
                    ):
                        errors.setdefault('variants', []).append(f'Each variant must include {attribute.name}.')
                elif validate_specifications and (
                    attribute.key not in specifications or specifications[attribute.key] in (None, '', [])
                ):
                    errors.setdefault('specifications', []).append(f'{attribute.name} is required.')
            if errors:
                raise serializers.ValidationError(errors)
        return attrs

    @staticmethod
    def _inherit_catalog_fields(validated_data, catalog_product, instance=None):
        fields = {
            'name': catalog_product.name,
            'brand': catalog_product.brand,
            'category': catalog_product.category,
            'tags': catalog_product.tags,
            'specifications': catalog_product.specifications,
            'short_description': catalog_product.short_description,
            'long_description': catalog_product.long_description,
            'description': catalog_product.long_description,
        }
        for field, value in fields.items():
            validated_data[field] = value
        if instance is None and 'catalog_image_references' not in validated_data:
            validated_data['catalog_image_references'] = list(catalog_product.image_references or [])

    def get_image_url(self, obj):
        if obj.image:
            return obj.image.url
        references = obj.catalog_image_references
        if not references and obj.catalog_product_id:
            references = obj.catalog_product.image_references
        if references:
            try:
                from cloudinary.utils import cloudinary_url
                return cloudinary_url(references[0])[0]
            except Exception:
                return None
        return obj.image_url or None

    def get_catalog_product(self, obj):
        if not obj.catalog_product_id:
            return None
        product = obj.catalog_product
        variants = getattr(product, '_prefetched_objects_cache', {}).get('variants')
        if variants is None:
            variants = list(product.variants.all())
        active_variants = [variant for variant in variants if variant.is_active]
        if active_variants:
            variant_data = [
                {'options': variant.options, 'image_references': variant.image_references}
                for variant in active_variants
            ]
        elif variants:
            variant_data = []
        else:
            variant_data = [
                {'options': options, 'image_references': []}
                for options in product.variant_options or []
                if isinstance(options, dict) and options
            ]
        return {
            'id': product.pk,
            'name': product.name,
            'brand': product.brand,
            'model': product.model,
            'product_type': product.product_type,
            'category_id': product.category_id,
            'variant_options': product.get_variant_options(),
            'variants': variant_data,
            'image_references': product.image_references,
        }

    def get_public_product_id(self, obj):
        try:
            return obj.public_product.pk
        except ObjectDoesNotExist:
            return None

    def get_review_status(self, obj):
        try:
            return obj.public_product.review_status
        except ObjectDoesNotExist:
            return 'pending_review'

    def get_review_note(self, obj):
        try:
            return obj.public_product.review_note
        except ObjectDoesNotExist:
            return ''

    def get_variant_list(self, obj):
        try:
            variants = ProductVariant.objects.filter(product=obj.public_product).annotate(
                sold_quantity=Sum('order_items__quantity'),
                has_inventory_item=Exists(
                    TraderInventoryItem.objects.filter(variant_id=OuterRef('pk')),
                ),
            )
            return ProductVariantSerializer(variants, many=True, context=self.context).data
        except ObjectDoesNotExist:
            return []


class TraderSaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraderSale
        fields = ('id', 'uuid', 'product', 'product_name', 'quantity', 'unit_price', 'total', 'note', 'created_at')
        read_only_fields = ('id', 'uuid', 'created_at')


class TraderExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraderExpense
        fields = ('id', 'uuid', 'description', 'amount', 'date', 'note', 'created_at')
        read_only_fields = ('id', 'uuid', 'created_at')


class TraderInventoryItemSerializer(serializers.ModelSerializer):
    product_name  = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()
    product_price = serializers.SerializerMethodField()
    product_stock = serializers.SerializerMethodField()
    product_uuid  = serializers.CharField(source='product.uuid', read_only=True)
    variant_options = serializers.SerializerMethodField()
    variant_sku = serializers.CharField(source='variant.sku', read_only=True, default='')

    class Meta:
        model = TraderInventoryItem
        fields = ('id', 'product', 'variant', 'variant_options', 'variant_sku', 'product_uuid',
                  'product_name', 'product_image', 'product_price', 'product_stock', 'quantity',
                  'cost_price', 'location', 'note', 'updated_at', 'created_at')
        read_only_fields = ('id', 'product_uuid', 'product_name', 'product_image', 'product_price',
                            'product_stock', 'variant_options', 'variant_sku', 'updated_at', 'created_at')

    def get_product_price(self, obj):
        try:
            return obj.variant.price if obj.variant_id else obj.product.price
        except ObjectDoesNotExist:
            return obj.product.price

    def get_product_stock(self, obj):
        try:
            return obj.variant.stock if obj.variant_id else obj.product.stock
        except ObjectDoesNotExist:
            return obj.product.stock

    def get_variant_options(self, obj):
        return obj.variant.options if obj.variant_id and obj.variant else {}

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


class TraderEarningSerializer(serializers.ModelSerializer):
    return_request_status = serializers.SerializerMethodField()

    class Meta:
        model = TraderEarning
        fields = (
            'id', 'order_code', 'product_name', 'quantity', 'listed_unit_price',
            'seller_amount', 'commission_pct', 'commission_amount', 'available_at',
            'status', 'return_request_status', 'created_at',
        )
        read_only_fields = fields

    def get_return_request_status(self, obj):
        if not obj.order_id:
            return None
        try:
            return obj.order.return_request.status
        except ObjectDoesNotExist:
            return None


class TraderWithdrawalSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraderWithdrawal
        fields = (
            'id', 'amount', 'fee', 'payout_amount', 'payout_method', 'payout_provider',
            'payout_account_name', 'payout_account_number', 'payout_branch', 'status',
            'transfer_reference', 'admin_note', 'processed_at', 'created_at',
        )
        read_only_fields = fields


class AdminTraderWithdrawalSerializer(TraderWithdrawalSerializer):
    trader_name = serializers.CharField(source='trader.business_name', read_only=True)
    trader_email = serializers.EmailField(source='trader.email', read_only=True)

    class Meta(TraderWithdrawalSerializer.Meta):
        fields = TraderWithdrawalSerializer.Meta.fields + ('trader_name', 'trader_email')


class TraderOrderItemSerializer(serializers.ModelSerializer):
    order_code        = serializers.CharField(source='order_item.order.code', read_only=True)
    order_status      = serializers.CharField(source='order_item.order.status', read_only=True)
    order_created_at  = serializers.DateTimeField(source='order_item.order.created_at', read_only=True)
    product_name      = serializers.CharField(source='order_item.product.name', read_only=True)
    product_image     = serializers.SerializerMethodField()
    variant_options   = serializers.JSONField(source='order_item.variant_options', read_only=True)
    variant_sku       = serializers.CharField(source='order_item.variant_sku', read_only=True)
    quantity          = serializers.IntegerField(source='order_item.quantity', read_only=True)
    price             = serializers.DecimalField(source='order_item.price', max_digits=10, decimal_places=2, read_only=True)
    order_item_id     = serializers.IntegerField(source='order_item.id', read_only=True)
    status_changed_by_name = serializers.CharField(source='status_changed_by.name', read_only=True, default=None)
    ready_at          = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TraderOrderItem
        fields = (
            'id', 'order_item_id', 'order_code', 'order_status', 'order_created_at',
            'product_name', 'product_image', 'variant_options', 'variant_sku', 'quantity', 'price',
            'status', 'note', 'status_changed_by_name', 'ready_at', 'updated_at',
        )
        read_only_fields = ('id', 'order_item_id', 'order_code', 'order_status', 'order_created_at',
                            'product_name', 'product_image', 'variant_options', 'variant_sku', 'quantity', 'price',
                            'status_changed_by_name', 'updated_at')

    def get_product_image(self, obj):
        try:
            return obj.order_item.product.image.url
        except Exception:
            return None
