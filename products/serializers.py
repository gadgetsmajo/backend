import json

from rest_framework import serializers
from django.utils.text import slugify
from django.db import transaction
from django.db.models import Avg, Count
from .models import Category, CategoryAttribute, Product, ProductImage, ProductVariant, FlashSale, ProductReview, ReviewImage
from settings_app.pricing import price_with_platform_charges


class CategoryAttributeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategoryAttribute
        fields = (
            'id', 'name', 'key', 'input_type', 'choices', 'is_required',
            'is_variant', 'is_filterable', 'position',
        )
        read_only_fields = ('id',)
        extra_kwargs = {'key': {'required': False}}

    def validate(self, attrs):
        key = attrs.get('key') or slugify(attrs.get('name', ''))
        if not key:
            raise serializers.ValidationError({'key': 'Provide a name for this attribute.'})
        attrs['key'] = key
        choices = attrs.get('choices', [])
        if not isinstance(choices, list) or any(not isinstance(choice, str) or not choice.strip() for choice in choices):
            raise serializers.ValidationError({'choices': 'Choices must be a list of non-empty strings.'})
        if attrs.get('input_type') not in ('dropdown', 'multi_select') and choices:
            raise serializers.ValidationError({'choices': 'Choices are supported only for dropdown and multi-select attributes.'})
        if attrs.get('input_type') in ('dropdown', 'multi_select') and not choices:
            raise serializers.ValidationError({'choices': 'Add at least one choice for this attribute type.'})
        return attrs


class CategorySerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, allow_null=True)
    parent_id = serializers.PrimaryKeyRelatedField(
        source='parent', queryset=Category.objects.all(), required=False, allow_null=True,
    )
    attributes = CategoryAttributeSerializer(many=True, required=False)

    class Meta:
        model = Category
        fields = ('id', 'uuid', 'name', 'slug', 'image', 'parent_id', 'attributes')
        extra_kwargs = {'slug': {'required': False}}

    def to_internal_value(self, data):
        data = data.copy()
        if data.get('parent_id') == '':
            data['parent_id'] = None
        attributes = data.get('attributes')
        if isinstance(attributes, str):
            try:
                data['attributes'] = json.loads(attributes)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError({'attributes': 'Enter valid JSON.'}) from exc
        return super().to_internal_value(data)

    def validate(self, attrs):
        slug = attrs.get('slug') or slugify(attrs.get('name', ''))
        if not self.instance:
            original = slug
            counter = 1
            while Category.objects.filter(slug=slug).exists():
                slug = f'{original}-{counter}'
                counter += 1
        attrs['slug'] = slug
        parent = attrs.get('parent', getattr(self.instance, 'parent', None))
        current_parent = parent
        while current_parent:
            if self.instance and current_parent.pk == self.instance.pk:
                raise serializers.ValidationError({'parent_id': 'A category cannot be its own ancestor.'})
            current_parent = current_parent.parent
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        attributes = validated_data.pop('attributes', None)
        category = super().create(validated_data)
        if attributes is not None:
            self._save_attributes(category, attributes)
        return category

    @transaction.atomic
    def update(self, instance, validated_data):
        attributes = validated_data.pop('attributes', None)
        category = super().update(instance, validated_data)
        if attributes is not None:
            self._save_attributes(category, attributes)
        return category

    @staticmethod
    def _save_attributes(category, attributes):
        submitted_keys = set()
        for attribute in attributes:
            key = attribute['key']
            if key in submitted_keys:
                raise serializers.ValidationError({'attributes': f'Duplicate attribute key: {key}.'})
            submitted_keys.add(key)
            CategoryAttribute.objects.update_or_create(
                category=category, key=key, defaults=attribute,
            )
        category.attributes.exclude(key__in=submitted_keys).delete()

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        if instance.image:
            try:
                rep['image'] = instance.image.url
            except Exception:
                rep['image'] = None
        return rep


class ProductVariantSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    listed_price = serializers.DecimalField(source='price', max_digits=10, decimal_places=2, read_only=True)
    compare_at_listed_price = serializers.DecimalField(
        source='compare_at_price', max_digits=10, decimal_places=2, read_only=True,
    )

    class Meta:
        model = ProductVariant
        fields = (
            'id', 'sku', 'options', 'price', 'listed_price',
            'compare_at_price', 'compare_at_listed_price', 'stock',
            'weight', 'image', 'image_url', 'is_active',
        )
        read_only_fields = ('id', 'image_url')
        extra_kwargs = {'sku': {'validators': []}}

    def validate_options(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError('Each variant must have at least one option value.')
        if any(not isinstance(key, str) or not key.strip() for key in value):
            raise serializers.ValidationError('Variant option names must be non-empty strings.')
        if any(not isinstance(option, (str, int, float, bool)) for option in value.values()):
            raise serializers.ValidationError('Variant option values must be simple values.')
        return value

    def validate(self, attrs):
        price = attrs.get('price', getattr(self.instance, 'price', None))
        compare_at_price = attrs.get('compare_at_price', getattr(self.instance, 'compare_at_price', None))
        if price is not None and price <= 0:
            raise serializers.ValidationError({'price': 'Variant price must be greater than zero.'})
        if compare_at_price is not None and price is not None and compare_at_price < price:
            raise serializers.ValidationError({'compare_at_price': 'Compare-at price must be at least the variant price.'})
        return attrs

    def get_image_url(self, obj):
        try:
            return obj.image.url if obj.image else None
        except Exception:
            return None

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['price'] = str(price_with_platform_charges(instance.price))
        if instance.compare_at_price:
            rep['compare_at_price'] = str(price_with_platform_charges(instance.compare_at_price))
        return rep


def sync_product_variants(product, variants):
    existing = list(product.variants.all())
    by_options = {
        json.dumps(variant.options, sort_keys=True, separators=(',', ':')): variant
        for variant in existing
    }
    submitted = [
        (variant, by_options.pop(
            json.dumps(variant['options'], sort_keys=True, separators=(',', ':')),
            None,
        ))
        for variant in variants
    ]
    retained_ids = [variant.pk for _, variant in submitted if variant]
    product.variants.exclude(pk__in=retained_ids).delete()
    if retained_ids:
        product.variants.filter(pk__in=retained_ids).update(sku='')

    for data, variant in submitted:
        if variant is None:
            ProductVariant.objects.create(product=product, **data)
            continue
        for field, value in data.items():
            setattr(variant, field, value)
        variant.save()


class ProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ('id', 'url', 'order')

    def get_url(self, obj):
        try:
            return obj.image.url
        except Exception:
            return None


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True,
        required=False, allow_null=True,
    )
    listed_price = serializers.DecimalField(source='price', max_digits=10, decimal_places=2, read_only=True)
    image_url = serializers.SerializerMethodField(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    is_featured = serializers.BooleanField(required=False)
    is_new_deal = serializers.BooleanField(required=False)
    reviews_count = serializers.SerializerMethodField()
    seller_uuid = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = ('id', 'uuid', 'name', 'slug', 'category', 'category_id',
                  'brand', 'condition', 'tags', 'specifications', 'review_status', 'review_note', 'variants',
                  'price', 'listed_price', 'original_price', 'image_url', 'images',
                  'short_description', 'long_description', 'delivery_fee',
                  'rating', 'stock', 'is_active', 'is_featured', 'is_new_deal', 'seller_uuid', 'seller_name',
                  'created_at', 'reviews_count')
        read_only_fields = (
            'id', 'uuid', 'slug', 'rating', 'created_at',
            'review_status', 'review_note',
        )

    def to_internal_value(self, data):
        data = data.copy()
        for field in ('tags', 'specifications', 'variants'):
            value = data.get(field)
            if isinstance(value, str):
                try:
                    data[field] = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise serializers.ValidationError({field: 'Enter valid JSON.'}) from exc
        if isinstance(data.get('variants'), list):
            request = self.context.get('request')
            files = request.FILES if request else {}
            for index, variant in enumerate(data['variants']):
                image = files.get(f'variant_image_{index}')
                if image and isinstance(variant, dict):
                    variant['image'] = image
        if data.get('category_id') == '':
            data['category_id'] = None
        return super().to_internal_value(data)

    def get_reviews_count(self, obj):
        return obj.reviews.filter(status='published').count()

    def get_seller_uuid(self, obj):
        trader = obj.trader or (obj.trader_product.trader if obj.trader_product_id else None)
        if (
            not trader
            or trader.status != 'approved'
            or not trader.is_visible
            or trader.is_closed
        ):
            return None
        return str(trader.uuid)

    def get_seller_name(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_staff:
            return None
        trader = obj.trader or (obj.trader_product.trader if obj.trader_product_id else None)
        return trader.business_name if trader else None

    def validate_specifications(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Specifications must be an object of attribute names and values.')
        if any(not isinstance(key, str) or not key.strip() for key in value):
            raise serializers.ValidationError('Specification names must be non-empty strings.')
        return value

    def validate_tags(self, value):
        if not isinstance(value, list) or any(not isinstance(tag, str) or not tag.strip() for tag in value):
            raise serializers.ValidationError('Tags must be a list of non-empty strings.')
        return value

    def validate(self, attrs):
        category = attrs.get('category', getattr(self.instance, 'category', None))
        specifications = attrs.get('specifications', getattr(self.instance, 'specifications', {}))
        variants = attrs.get('variants')
        if variants is not None:
            if len(variants) > 100:
                raise serializers.ValidationError({'variants': 'A product cannot have more than 100 variants.'})
            skus = [variant.get('sku', '').strip().casefold() for variant in variants if variant.get('sku', '').strip()]
            if len(skus) != len(set(skus)):
                raise serializers.ValidationError({'variants': 'Each variant SKU must be unique.'})
            product_variants = ProductVariant.objects.all()
            if self.instance:
                product_variants = product_variants.exclude(product=self.instance)
            for sku in skus:
                if product_variants.filter(sku__iexact=sku).exists():
                    raise serializers.ValidationError({'variants': f'SKU {sku} is already in use.'})
            option_sets = [
                tuple(sorted((key, str(value)) for key, value in variant.get('options', {}).items()))
                for variant in variants
            ]
            if len(option_sets) != len(set(option_sets)):
                raise serializers.ValidationError({'variants': 'Variant option combinations must be unique.'})
        if category:
            errors = {}
            for attribute in category.attributes.filter(is_required=True):
                if attribute.is_variant:
                    if variants is not None and (
                        not variants or any(attribute.key not in variant.get('options', {}) for variant in variants)
                    ):
                        errors.setdefault('variants', []).append(f'Each variant must include {attribute.name}.')
                    elif variants is None and self.instance is None:
                        errors.setdefault('variants', []).append(f'At least one variant with {attribute.name} is required.')
                elif attribute.key not in specifications or specifications[attribute.key] in (None, '', []):
                    errors.setdefault('specifications', []).append(f'{attribute.name} is required.')
            if errors:
                raise serializers.ValidationError(errors)
        return attrs

    def get_image_url(self, obj):
        if obj.image:
            try:
                return obj.image.url
            except Exception:
                pass
        return None

    @transaction.atomic
    def create(self, validated_data):
        variants = validated_data.pop('variants', [])
        validated_data['is_active'] = True
        product = super().create(validated_data)
        for variant in variants:
            ProductVariant.objects.create(product=product, **variant)
        if variants:
            product.price = min(variant['price'] for variant in variants)
            product.stock = sum(variant['stock'] for variant in variants)
            product.save(update_fields=('price', 'stock'))
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        variants = validated_data.pop('variants', None)
        product = super().update(instance, validated_data)
        if variants is not None:
            sync_product_variants(product, variants)
            if variants:
                product.price = min(variant['price'] for variant in variants)
                product.stock = sum(variant['stock'] for variant in variants)
                product.save(update_fields=('price', 'stock'))
        return product

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['image'] = rep.get('image_url')
        rep['price'] = str(price_with_platform_charges(instance.price))
        if instance.original_price:
            rep['original_price'] = str(price_with_platform_charges(instance.original_price))
        return rep


class ReviewImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ReviewImage
        fields = ('id', 'url', 'uploaded_at')

    def get_url(self, obj):
        try:
            url = obj.image.url
            return url if url else None
        except Exception:
            return None


class ProductReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True)
    user_avatar = serializers.SerializerMethodField()
    images = ReviewImageSerializer(many=True, read_only=True)
    order = serializers.PrimaryKeyRelatedField(read_only=True)
    order_item = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ProductReview
        fields = (
            'id', 'user_name', 'user_avatar',
            'overall_rating', 'performance_rating', 'battery_life_rating',
            'product_quality_rating', 'condition_rating', 'value_for_money_rating',
            'design_rating', 'features_rating', 'size_fit_rating',
            'review_text', 'verified_purchase', 'status',
            'images',
            'order', 'order_item',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'user_name', 'user_avatar', 'verified_purchase',
                            'status', 'images', 'created_at', 'updated_at')
        extra_kwargs = {
            'overall_rating': {'min_value': 1, 'max_value': 5},
            'performance_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'battery_life_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'product_quality_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'condition_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'value_for_money_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'design_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'features_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'size_fit_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'review_text': {'required': False, 'allow_blank': True, 'max_length': 500},
        }

    def get_user_avatar(self, obj):
        try:
            url = obj.user.avatar.url
            return url if url else None
        except Exception:
            return None

    def create(self, validated_data):
        return ProductReview.objects.create(**validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('order', None)
        validated_data.pop('order_item', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        return instance


class RatingSummarySerializer(serializers.Serializer):
    average = serializers.FloatField()
    total = serializers.IntegerField()
    breakdown = serializers.DictField(child=serializers.IntegerField())
    with_photos = serializers.IntegerField()


class FlashSaleSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    base_flash_price = serializers.DecimalField(source='flash_price', max_digits=10, decimal_places=2, read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), source='product', write_only=True
    )
    stock_left = serializers.IntegerField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    discount_pct = serializers.SerializerMethodField()

    class Meta:
        model = FlashSale
        fields = ('id', 'product', 'product_id', 'flash_price', 'base_flash_price', 'ends_at',
                  'stock_limit', 'stock_sold', 'stock_left', 'is_active',
                  'is_expired', 'discount_pct', 'created_at')
        read_only_fields = ('id', 'stock_sold', 'created_at')

    def get_discount_pct(self, obj):
        orig = obj.product.original_price or obj.product.price
        commissioned_flash = price_with_platform_charges(obj.flash_price)
        commissioned_orig = price_with_platform_charges(orig)
        if commissioned_orig and commissioned_orig > commissioned_flash:
            return round((1 - commissioned_flash / commissioned_orig) * 100)
        return 0

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['flash_price'] = str(price_with_platform_charges(instance.flash_price))
        return rep

    def validate(self, attrs):
        from django.utils import timezone
        product = attrs.get('product') or (self.instance.product if self.instance else None)
        flash_price = attrs.get('flash_price')
        stock_limit = attrs.get('stock_limit')
        ends_at = attrs.get('ends_at')

        if product is None:
            raise serializers.ValidationError({'product_id': 'Product is required.'})

        # flash_price must be less than the product's current price
        if flash_price is not None and flash_price >= product.price:
            raise serializers.ValidationError({
                'flash_price': f'Flash price must be less than the product price (UGX {product.price:,.0f}).'
            })

        # stock_limit must not exceed available product stock
        if stock_limit is not None and stock_limit > product.stock:
            raise serializers.ValidationError({
                'stock_limit': f'Stock limit ({stock_limit}) cannot exceed available product stock ({product.stock}).'
            })

        # ends_at must be in the future
        if ends_at is not None and ends_at <= timezone.now():
            raise serializers.ValidationError({
                'ends_at': 'End time must be in the future.'
            })

        # prevent duplicate active flash sale for the same product
        if product:
            qs = FlashSale.objects.filter(
                product=product,
                is_active=True,
                ends_at__gt=timezone.now(),
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    'product_id': f'"{product.name}" already has an active flash sale.'
                })

        return attrs
