import json

from rest_framework import serializers
from django.core.exceptions import ObjectDoesNotExist
from django.utils.text import slugify
from django.utils import timezone
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from .models import (
    CatalogVariant, Category, CategoryAttribute, Product, ProductImage, ProductVariant,
    FlashSale, ProductReview, ReviewImage,
)
from settings_app.pricing import price_with_platform_charges


def to_plain_data(data):
    return {key: data.get(key) for key in data}


class TruncatedCharField(serializers.CharField):
    def to_internal_value(self, data):
        if isinstance(data, str) and self.max_length is not None:
            data = data[:self.max_length]
        return super().to_internal_value(data)


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
        input_type = attrs.get('input_type', getattr(self.instance, 'input_type', None))
        choices = attrs.get('choices', getattr(self.instance, 'choices', []))
        attrs['choices'] = choices
        if not isinstance(choices, list) or any(not isinstance(choice, str) or not choice.strip() for choice in choices):
            raise serializers.ValidationError({'choices': 'Choices must be a list of non-empty strings.'})
        if input_type not in ('dropdown', 'multi_select', 'text', 'size', 'color') and choices:
            raise serializers.ValidationError({'choices': 'Choices are supported only for text, size, color, dropdown, and multi-select attributes.'})
        if input_type in ('dropdown', 'multi_select') and not choices:
            raise serializers.ValidationError({'choices': 'Add at least one choice for this attribute type.'})
        return attrs


class CategorySerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, allow_null=True)
    parent_id = serializers.PrimaryKeyRelatedField(
        source='parent', queryset=Category.objects.all(), required=False, allow_null=True,
    )
    attributes = CategoryAttributeSerializer(many=True, required=False)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            'id', 'uuid', 'name', 'slug', 'description', 'image', 'parent_id',
            'is_active', 'position', 'product_count', 'attributes',
        )
        extra_kwargs = {'slug': {'required': False}}

    def get_product_count(self, obj):
        return getattr(obj, 'product_count', 0)

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
        depth = 1
        while current_parent:
            if self.instance and current_parent.pk == self.instance.pk:
                raise serializers.ValidationError({'parent_id': 'A category cannot be its own ancestor.'})
            current_parent = current_parent.parent
            depth += 1
        if depth > 3:
            raise serializers.ValidationError({'parent_id': 'Categories can be nested up to three levels.'})
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
    sold_quantity = serializers.SerializerMethodField()
    has_inventory_item = serializers.SerializerMethodField()
    listed_price = serializers.DecimalField(source='price', max_digits=10, decimal_places=2, read_only=True)
    compare_at_listed_price = serializers.DecimalField(
        source='compare_at_price', max_digits=10, decimal_places=2, read_only=True,
    )

    class Meta:
        model = ProductVariant
        fields = (
            'id', 'sku', 'options', 'price', 'listed_price',
            'compare_at_price', 'compare_at_listed_price', 'stock',
            'weight', 'image', 'image_url', 'is_active', 'sold_quantity', 'has_inventory_item',
        )
        read_only_fields = ('id', 'image_url', 'sold_quantity', 'has_inventory_item')
        extra_kwargs = {'sku': {'validators': []}}

    def validate_options(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError('Each variant must have at least one option value.')
        if any(not isinstance(key, str) or not key.strip() for key in value):
            raise serializers.ValidationError('Variant option names must be non-empty strings.')
        if any(not isinstance(option, (str, int, float, bool)) for option in value.values()):
            raise serializers.ValidationError('Variant option values must be simple values.')
        if any(isinstance(option, str) and not option.strip() for option in value.values()):
            raise serializers.ValidationError('Variant option values must not be empty.')
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
        if obj.image:
            try:
                return obj.image.url
            except Exception:
                return None
        if obj.catalog_variant_id and obj.catalog_variant.image_references:
            from cloudinary.utils import cloudinary_url

            try:
                return cloudinary_url(obj.catalog_variant.image_references[0])[0]
            except Exception:
                return None
        return None

    def get_sold_quantity(self, obj):
        if not self._can_view_inventory(obj):
            return 0
        if hasattr(obj, 'sold_quantity'):
            return obj.sold_quantity or 0
        return obj.order_items.aggregate(total=Sum('quantity'))['total'] or 0

    def get_has_inventory_item(self, obj):
        if not self._can_view_inventory(obj):
            return False
        if hasattr(obj, 'has_inventory_item'):
            return obj.has_inventory_item
        return obj.trader_inventory_items.exists()

    def _can_view_inventory(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        if obj.trader_product_id:
            trader = obj.trader_product.trader
        elif obj.product_id:
            product = obj.product
            trader = product.trader
            if not trader and product.trader_product_id:
                try:
                    trader = product.trader_product.trader
                except ObjectDoesNotExist:
                    return False
        else:
            return False
        return bool(
            trader
            and (
                trader.user_id == user.pk
                or trader.email.casefold() == (user.email or '').casefold()
            )
        )

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['price'] = str(price_with_platform_charges(instance.price))
        if instance.compare_at_price:
            rep['compare_at_price'] = str(price_with_platform_charges(instance.compare_at_price))
        if not self._can_view_inventory(instance):
            rep.pop('sold_quantity', None)
            rep.pop('has_inventory_item', None)
        return rep


def validate_variant_removals(product, variants):
    if not product:
        return
    retained_options = {
        json.dumps(variant.get('options', {}), sort_keys=True, separators=(',', ':'))
        for variant in variants
    }
    removable_candidates = []
    for variant in product.variants.all():
        option_key = json.dumps(variant.options, sort_keys=True, separators=(',', ':'))
        if option_key not in retained_options:
            removable_candidates.append(variant.pk)
    if not removable_candidates:
        return
    protected_ids = set(
        ProductVariant.objects.filter(pk__in=removable_candidates)
        .filter(
            Q(order_items__isnull=False)
            | Q(trader_inventory_items__isnull=False)
        )
        .values_list('pk', flat=True)
        .distinct()
    )
    if protected_ids:
        raise serializers.ValidationError({
            'variants': 'Variants with order or inventory history cannot be removed. Mark them unavailable instead.',
        })


def sync_product_variants(product, variants):
    existing = list(product.variants.all())
    offer_owner = product._meta.model_name == 'traderproduct'
    owner_fields = (
        {'trader_product': product}
        if offer_owner else {'product': product}
    )
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
            variant = ProductVariant.objects.create(**owner_fields, **data)
        else:
            for field, value in data.items():
                setattr(variant, field, value)
            variant.save()
        catalog_product_id = getattr(product, 'catalog_product_id', None)
        if catalog_product_id:
            options_key = CatalogVariant.make_options_key(variant.options)
            catalog_variant = CatalogVariant.objects.filter(
                catalog_product_id=catalog_product_id,
                options_key=options_key,
            ).first()
            catalog_product = product.catalog_product
            if catalog_variant is None and variant.options in catalog_product.get_variant_options():
                catalog_variant, _ = CatalogVariant.objects.get_or_create(
                    catalog_product_id=product.catalog_product_id,
                    options_key=options_key,
                    defaults={'options': variant.options},
                )
            if catalog_variant:
                variant.catalog_variant = catalog_variant
                variant.save(update_fields=('catalog_variant', 'updated_at'))

    from traders.models import TraderInventoryItem

    for variant in product.variants.all():
        TraderInventoryItem.objects.filter(variant_id=variant.pk).update(
            quantity=variant.stock,
            updated_at=timezone.now(),
        )


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
    short_description = TruncatedCharField(max_length=300, required=False, allow_blank=True)
    category = CategorySerializer(read_only=True)
    catalog_product_id = serializers.IntegerField(read_only=True, allow_null=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True,
        required=False, allow_null=True,
    )
    listed_price = serializers.DecimalField(source='price', max_digits=10, decimal_places=2, read_only=True)
    original_listed_price = serializers.DecimalField(
        source='original_price', max_digits=10, decimal_places=2, read_only=True,
    )
    image_url = serializers.SerializerMethodField(read_only=True)
    images = serializers.SerializerMethodField()
    is_featured = serializers.BooleanField(required=False)
    is_new_deal = serializers.BooleanField(required=False)
    reviews_count = serializers.SerializerMethodField()
    seller_uuid = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    seller_count = serializers.SerializerMethodField()
    trader_offer_id = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, required=False)
    availability = serializers.SerializerMethodField()
    warranty = serializers.SerializerMethodField()
    delivery_options = serializers.SerializerMethodField()
    package_details = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ('id', 'uuid', 'name', 'slug', 'category', 'category_id',
                  'brand', 'condition', 'tags', 'specifications', 'review_status', 'review_note', 'variants',
                  'catalog_product_id',
                  'price', 'listed_price', 'original_price', 'original_listed_price', 'image_url', 'images',
                  'short_description', 'long_description', 'delivery_fee',
                  'rating', 'stock', 'is_active', 'is_featured', 'is_new_deal', 'seller_uuid', 'seller_name',
                  'seller_count', 'trader_offer_id',
                  'availability', 'warranty', 'delivery_options', 'package_details',
                  'created_at', 'reviews_count')
        read_only_fields = (
            'id', 'uuid', 'slug', 'rating', 'created_at',
            'review_status', 'review_note',
        )

    def validate_category_id(self, category):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or user.is_staff or category is None:
            return category
        existing_assignment = self.instance is not None and self.instance.category_id == category.pk
        if not category.is_active and not existing_assignment:
            raise serializers.ValidationError('Choose an active marketplace category.')
        if category.children.filter(is_active=True).exists() and not existing_assignment:
            raise serializers.ValidationError('Choose a category or subcategory below this department.')
        return category

    def to_internal_value(self, data):
        data = to_plain_data(data)
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
        if obj.catalog_product_id:
            return ProductReview.objects.filter(
                product__catalog_product_id=obj.catalog_product_id,
                status='published',
            ).count()
        return obj.reviews.filter(status='published').count()

    def get_seller_uuid(self, obj):
        offer = self.context.get('trader_offer')
        if offer is not None:
            trader = offer.trader
            return str(trader.uuid) if trader.is_visible and not trader.is_closed else None
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
        offer = self.context.get('trader_offer')
        if offer is not None:
            trader = offer.trader
            return trader.business_name if trader.is_visible and not trader.is_closed else None
        trader = obj.trader or (obj.trader_product.trader if obj.trader_product_id else None)
        if (
            not trader
            or trader.status != 'approved'
            or not trader.is_visible
            or trader.is_closed
        ):
            return None
        return trader.business_name

    def _catalog_offers(self, obj):
        if not obj.is_catalog_anchor:
            return []
        prefetched = getattr(obj, '_prefetched_objects_cache', {}).get('trader_offers')
        if prefetched is None:
            from traders.models import TraderProduct

            prefetched = TraderProduct.objects.filter(
                Q(listing_product=obj)
                | Q(catalog_product__public_product=obj)
                | Q(legacy_public_product=obj),
                is_active=True,
                review_status='approved',
                trader__status='approved',
                trader__is_visible=True,
                trader__is_closed=False,
            ).select_related('trader')
        return [
            offer for offer in prefetched
            if offer.is_active
            and offer.review_status == 'approved'
            and offer.trader.status == 'approved'
            and offer.trader.is_visible
            and not offer.trader.is_closed
        ]

    def get_seller_count(self, obj):
        if self.context.get('trader_offer') is not None:
            return 1
        return len(self._catalog_offers(obj))

    def get_trader_offer_id(self, obj):
        offer = self.context.get('trader_offer')
        return offer.pk if offer is not None else None

    def _get_offer_value(self, obj, field, default):
        offer = self.context.get('trader_offer')
        if offer is not None:
            return getattr(offer, field, default)
        if obj.trader_product_id:
            return getattr(obj.trader_product, field, default)
        return default

    def get_availability(self, obj):
        return self._get_offer_value(obj, 'availability', 'in_stock')

    def get_warranty(self, obj):
        return self._get_offer_value(obj, 'warranty', '')

    def get_delivery_options(self, obj):
        return self._get_offer_value(obj, 'delivery_options', [])

    def get_package_details(self, obj):
        return self._get_offer_value(obj, 'package_details', '')

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
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if (
            self.instance
            and self.instance.catalog_product_id
            and user
            and user.is_authenticated
            and not user.is_staff
        ):
            protected_fields = {
                'name', 'brand', 'category', 'tags', 'specifications',
                'short_description', 'long_description',
            }
            changed_fields = protected_fields.intersection(attrs)
            if changed_fields:
                raise serializers.ValidationError({
                    field: 'This information is managed in the shared catalog.'
                    for field in sorted(changed_fields)
                })
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
            if self.instance:
                validate_variant_removals(self.instance, variants)
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
                    and (bool(variants) or self.instance.variants.exists())
                )
            )
            variant_data = variants
            if variant_data is None and self.instance and validate_variants:
                variant_data = [
                    {'options': variant.options}
                    for variant in self.instance.variants.all()
                ]
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

    def get_image_url(self, obj):
        if obj.image:
            try:
                return obj.image.url
            except Exception:
                pass
        return None

    def get_images(self, obj):
        serialized = list(ProductImageSerializer(obj.images.all(), many=True).data)
        if obj.trader_product_id and obj.trader_product.catalog_image_references:
            references = obj.trader_product.catalog_image_references
        elif obj.catalog_product_id:
            references = obj.catalog_product.image_references
        else:
            references = []
        if references:
            from cloudinary.utils import cloudinary_url

            for reference in references:
                try:
                    url = cloudinary_url(reference)[0]
                except Exception:
                    continue
                serialized.append({
                    'id': -(len(serialized) + 1),
                    'url': url,
                    'order': len(serialized),
                })
        return serialized

    @transaction.atomic
    def create(self, validated_data):
        variants = validated_data.pop('variants', [])
        validated_data['is_active'] = True
        product = super().create(validated_data)
        if variants:
            sync_product_variants(product, variants)
        if variants:
            product.price = min(variant['price'] for variant in variants)
            product.stock = sum(variant['stock'] for variant in variants)
            product.save(update_fields=('price', 'stock'))
            try:
                trader_product = product.trader_product
            except ObjectDoesNotExist:
                trader_product = None
            if trader_product:
                trader_product.price = product.price
                trader_product.stock = product.stock
                trader_product.save(update_fields=('price', 'stock', 'updated_at'))
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
        if instance.catalog_product_id:
            catalog = instance.catalog_product
            rep.update({
                'name': catalog.name,
                'brand': catalog.brand,
                'tags': catalog.tags,
                'specifications': catalog.specifications,
                'short_description': catalog.short_description,
                'long_description': catalog.long_description,
            })
            if catalog.category_id:
                rep['category'] = CategorySerializer(catalog.category).data
        rep['image'] = rep.get('image_url')

        offer = self.context.get('trader_offer')
        if offer is not None:
            base_price = offer.price
            rep['price'] = str(price_with_platform_charges(base_price))
            rep['listed_price'] = str(base_price)
            rep['original_price'] = (
                str(price_with_platform_charges(offer.original_price))
                if offer.original_price else None
            )
            rep['original_listed_price'] = (
                str(offer.original_price) if offer.original_price else None
            )
            rep['stock'] = offer.stock
            rep['delivery_fee'] = str(offer.delivery_fee)
            rep['is_active'] = offer.is_active
            rep['review_status'] = offer.review_status
            rep['review_note'] = offer.review_note
            rep['variants'] = ProductVariantSerializer(
                offer.variants.all(), many=True, context=self.context,
            ).data
        elif instance.trader_product_id:
            rep['variants'] = ProductVariantSerializer(
                instance.trader_product.variants.all(),
                many=True,
                context=self.context,
            ).data
        elif instance.is_catalog_anchor:
            offers = self._catalog_offers(instance)
            available_offers = [offer for offer in offers if offer.stock > 0]
            if available_offers:
                lowest_offer = min(available_offers, key=lambda offer: (offer.price, offer.pk))
                rep['price'] = str(price_with_platform_charges(lowest_offer.price))
                rep['listed_price'] = str(lowest_offer.price)
                rep['original_price'] = (
                    str(price_with_platform_charges(lowest_offer.original_price))
                    if lowest_offer.original_price else None
                )
                rep['original_listed_price'] = (
                    str(lowest_offer.original_price) if lowest_offer.original_price else None
                )
                rep['stock'] = sum(offer.stock for offer in available_offers)
            else:
                rep['price'] = '0.00'
                rep['listed_price'] = '0.00'
                rep['stock'] = 0

        if not instance.is_catalog_anchor and offer is None:
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
