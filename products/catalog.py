import json
import re
from difflib import SequenceMatcher
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CatalogProduct, CatalogProductImage, CatalogVariant, Category, Product, ProductVariant
from .pagination import ProductPagination
from .serializers import ProductSerializer, ProductVariantSerializer
from .visibility import public_marketplace_product_filter
from traders.models import TraderApplication, TraderProduct


OFFER_ONLY_FIELDS = {
    'price', 'original_price', 'stock', 'trader_sku', 'sku', 'condition',
    'delivery_fee', 'availability', 'warranty',
}


@transaction.atomic
def merge_catalog_products(source_ids, survivor_id):
    source_ids = {int(source_id) for source_id in source_ids} - {int(survivor_id)}
    if not source_ids:
        raise ValueError('Select at least one source product to merge.')

    products = list(
        CatalogProduct.objects.select_for_update()
        .filter(pk__in=source_ids | {int(survivor_id)})
        .order_by('pk')
    )
    by_id = {product.pk: product for product in products}
    if int(survivor_id) not in by_id or source_ids.difference(by_id):
        raise CatalogProduct.DoesNotExist('A selected catalog product no longer exists.')

    survivor = by_id[int(survivor_id)]
    sources = [by_id[pk] for pk in sorted(source_ids)]

    for source in sources:
        for field in ('brand', 'model', 'product_type', 'short_description', 'long_description'):
            if not getattr(survivor, field):
                setattr(survivor, field, getattr(source, field))
        if not survivor.category_id:
            survivor.category_id = source.category_id
        for field in ('specifications', 'attributes', 'identifiers'):
            current = getattr(survivor, field)
            additional = getattr(source, field)
            if isinstance(current, dict) and isinstance(additional, dict):
                setattr(survivor, field, {**additional, **current})
        survivor.tags = list(dict.fromkeys([*(survivor.tags or []), *(source.tags or [])]))
        for field in ('image_references', 'variant_options'):
            current = list(getattr(survivor, field) or [])
            seen = {
                json.dumps(value, sort_keys=True, separators=(',', ':'))
                for value in current
            }
            for value in getattr(source, field) or []:
                key = json.dumps(value, sort_keys=True, separators=(',', ':'))
                if key not in seen:
                    current.append(value)
                    seen.add(key)
            setattr(survivor, field, current)

        for source_variant in source.variants.all():
            target_variant = survivor.variants.filter(
                options_key=source_variant.options_key,
            ).first()
            if target_variant:
                target_variant.image_references = list(dict.fromkeys([
                    *(target_variant.image_references or []),
                    *(source_variant.image_references or []),
                ]))
                target_variant.is_active = target_variant.is_active or source_variant.is_active
                target_variant.save(update_fields=('image_references', 'is_active'))
                ProductVariant.objects.filter(catalog_variant=source_variant).update(
                    catalog_variant=target_variant,
                )
                source_variant.delete()
            else:
                source_variant.catalog_product = survivor
                source_variant.save(update_fields=('catalog_product',))

    source_pk_list = [source.pk for source in sources]
    CatalogProduct.objects.filter(pk__in=source_pk_list).update(identity_key='')
    survivor.save()

    Product.objects.filter(catalog_product_id__in=source_pk_list).update(
        catalog_product_id=survivor.pk,
    )
    from traders.models import TraderProduct

    catalog_anchor = survivor.public_product
    if catalog_anchor is None:
        catalog_anchor = next(
            (source.public_product for source in sources if source.public_product_id),
            None,
        )
        if catalog_anchor:
            survivor.public_product = catalog_anchor
            survivor.save(update_fields=('public_product', 'updated_at'))
    if catalog_anchor:
        Product.objects.filter(
            catalog_product_id=survivor.pk,
        ).exclude(pk=catalog_anchor.pk).update(is_catalog_anchor=False)
        Product.objects.filter(pk=catalog_anchor.pk).update(is_catalog_anchor=True)
        TraderProduct.objects.filter(catalog_product_id=survivor.pk).update(
            listing_product_id=catalog_anchor.pk,
        )
    for source in sources:
        if source.public_product_id:
            source.public_product.is_catalog_anchor = False
            source.public_product.save(update_fields=('is_catalog_anchor',))
            source.public_product = None
            source.save(update_fields=('public_product', 'updated_at'))

    TraderProduct.objects.filter(catalog_product_id__in=source_pk_list).update(
        catalog_product_id=survivor.pk,
    )
    if catalog_anchor:
        TraderProduct.objects.filter(catalog_product_id=survivor.pk).update(
            listing_product_id=catalog_anchor.pk,
        )
    CatalogProduct.objects.filter(pk__in=source_pk_list).update(
        review_status='disabled',
        is_active=False,
        review_note=f'Merged into catalog product {survivor.pk}.',
    )
    return survivor, len(source_pk_list)


def _normalized(value):
    return ' '.join(re.findall(r'[a-z0-9]+', str(value or '').casefold()))


def _identifier_values(identifiers):
    if isinstance(identifiers, dict):
        values = identifiers.values()
    elif isinstance(identifiers, list):
        values = identifiers
    else:
        return []
    return [
        _normalized(item)
        for value in values
        for item in (value if isinstance(value, list) else [value])
        if isinstance(item, (str, int)) and _normalized(item)
    ]


def _candidate_data(product):
    return {
        'id': product.pk,
        'name': product.name,
        'brand': product.brand,
        'model': product.model,
        'product_type': product.product_type,
        'category_id': product.category_id,
        'category_name': product.category.name if product.category_id else None,
        'image_references': product.image_references,
    }


def _find_similar_products(data):
    name = _normalized(data.get('name'))
    brand = _normalized(data.get('brand'))
    model = _normalized(data.get('model'))
    identifiers = set(_identifier_values(data.get('identifiers', {})))
    category_id = getattr(data.get('category'), 'pk', None)
    incoming_tokens = set(name.split())
    matches = []

    candidates = CatalogProduct.objects.select_related('category')
    for candidate in candidates.iterator():
        existing_name = _normalized(candidate.name)
        existing_brand = _normalized(candidate.brand)
        existing_model = _normalized(candidate.model)
        existing_identifiers = set(_identifier_values(candidate.identifiers))
        same_brand = not brand or not existing_brand or brand == existing_brand
        same_category = not category_id or not candidate.category_id or category_id == candidate.category_id

        duplicate = bool(identifiers & existing_identifiers)
        duplicate = duplicate or bool(model and existing_model and same_brand and model == existing_model)
        if not duplicate and same_brand and same_category and name and existing_name:
            existing_tokens = set(existing_name.split())
            short_tokens, long_tokens = sorted(
                (incoming_tokens, existing_tokens), key=len,
            )
            duplicate = (
                name == existing_name
                or (
                    len(short_tokens) >= 2
                    and short_tokens.issubset(long_tokens)
                )
                or SequenceMatcher(None, name, existing_name).ratio() >= 0.9
            )
        if duplicate:
            matches.append(candidate)
            if len(matches) == 10:
                break
    return matches


class CatalogProductSerializer(serializers.ModelSerializer):
    category_id = serializers.IntegerField(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True, default=None)
    variant_options = serializers.SerializerMethodField()
    variants = serializers.SerializerMethodField()

    def get_variant_options(self, obj):
        return obj.get_variant_options()

    def get_variants(self, obj):
        variants = getattr(obj, '_prefetched_objects_cache', {}).get('variants')
        if variants is None:
            variants = list(obj.variants.all())
        active_variants = [variant for variant in variants if variant.is_active]
        if active_variants:
            return [
                {'options': variant.options, 'image_references': variant.image_references}
                for variant in active_variants
            ]
        if variants:
            return []
        return [
            {'options': options, 'image_references': []}
            for options in obj.variant_options or []
            if isinstance(options, dict) and options
        ]

    class Meta:
        model = CatalogProduct
        fields = (
            'id', 'name', 'brand', 'model', 'product_type', 'category_id', 'category_name',
            'short_description', 'long_description', 'tags', 'specifications', 'attributes',
            'identifiers', 'variant_options', 'variants', 'image_references',
        )


class CatalogProductRequestSerializer(serializers.ModelSerializer):
    category_id = serializers.PrimaryKeyRelatedField(
        source='category', queryset=Category.objects.filter(is_active=True),
        required=False, allow_null=True,
    )
    offer_details = serializers.JSONField(write_only=True, required=True)
    images = serializers.ListField(
        child=serializers.ImageField(),
        required=False,
        write_only=True,
        max_length=12,
    )

    class Meta:
        model = CatalogProduct
        fields = (
            'name', 'brand', 'model', 'product_type', 'category_id',
            'short_description', 'long_description', 'tags', 'specifications',
            'attributes', 'identifiers', 'variant_options', 'offer_details', 'images',
        )

    def to_internal_value(self, data):
        forbidden = OFFER_ONLY_FIELDS.intersection(data.keys())
        if forbidden:
            raise serializers.ValidationError({
                field: 'Offer details belong to a trader offer, not a catalog product request.'
                for field in sorted(forbidden)
            })
        return super().to_internal_value(data)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Product name is required.')
        return value

    def validate(self, attrs):
        if not isinstance(attrs.get('identifiers', {}), dict):
            raise serializers.ValidationError({'identifiers': 'Identifiers must be an object.'})
        if not isinstance(attrs.get('specifications', {}), dict):
            raise serializers.ValidationError({'specifications': 'Specifications must be an object.'})
        if not isinstance(attrs.get('attributes', {}), dict):
            raise serializers.ValidationError({'attributes': 'Attributes must be an object.'})
        if not isinstance(attrs.get('tags', []), list):
            raise serializers.ValidationError({'tags': 'Tags must be a list.'})
        if not isinstance(attrs.get('variant_options', []), list):
            raise serializers.ValidationError({'variant_options': 'Variant options must be a list.'})
        if any(
            not isinstance(option, dict) or not option
            or any(
                not isinstance(key, str) or not key.strip()
                or not isinstance(value, (str, int, float, bool))
                or (isinstance(value, str) and not value.strip())
                for key, value in option.items()
            )
            for option in attrs.get('variant_options', [])
        ):
            raise serializers.ValidationError({
                'variant_options': 'Each variant must be an object with non-empty names and simple values.',
            })
        offer_details = attrs.get('offer_details')
        if offer_details is not None:
            offer_serializer = CatalogOfferRequestSerializer(data=offer_details)
            offer_serializer.is_valid(raise_exception=True)
            safe_offer_details = json.loads(json.dumps(
                offer_serializer.validated_data,
                cls=DjangoJSONEncoder,
            ))
            attrs['offer_details'] = safe_offer_details
            image_indexes = safe_offer_details.get('variant_image_indexes', [])
            images = attrs.get('images', [])
            variants = safe_offer_details.get('variants', [])
            option_keys = [
                CatalogVariant.make_options_key(variant['options'])
                for variant in variants
            ]
            if len(option_keys) != len(set(option_keys)):
                raise serializers.ValidationError({
                    'offer_details': 'Variant options must be unique.',
                })
            if image_indexes and len(image_indexes) != len(variants):
                raise serializers.ValidationError({
                    'offer_details': 'Provide one variant image index for each variant.',
                })
            if any(index is not None and index >= len(images) for index in image_indexes):
                raise serializers.ValidationError({
                    'offer_details': 'A variant image refers to a missing uploaded image.',
                })
            category = attrs.get('category', getattr(self.instance, 'category', None))
            if category:
                required_variants = list(category.attributes.filter(is_required=True, is_variant=True))
                variants = safe_offer_details.get('variants', [])
                for attribute in required_variants:
                    if not variants or any(
                        attribute.key not in variant.get('options', {})
                        or variant['options'].get(attribute.key) in (None, '')
                        for variant in variants
                    ):
                        raise serializers.ValidationError({
                            'offer_details': f'Every variant needs a value for {attribute.name}.',
                        })
                required_details = category.attributes.filter(is_required=True, is_variant=False)
                specifications = attrs.get(
                    'specifications',
                    getattr(self.instance, 'specifications', {}),
                )
                missing = [
                    attribute.name
                    for attribute in required_details
                    if specifications.get(attribute.key) in (None, '', [])
                ]
                if missing:
                    raise serializers.ValidationError({
                        'specifications': f'Required details are missing: {", ".join(missing)}.',
                    })
        if any(image.size > 10 * 1024 * 1024 for image in attrs.get('images', [])):
            raise serializers.ValidationError({'images': 'Each product image must be 10 MB or smaller.'})
        return attrs

    def create(self, validated_data):
        offer_details = validated_data.pop('offer_details')
        images = validated_data.pop('images', [])
        request = self.context.get('request')
        product = CatalogProduct.objects.create(
            **validated_data,
            request_offer_details=offer_details,
            created_by=request.user,
            review_status='pending_review',
            is_active=False,
        )
        image_indexes = offer_details.get('variant_image_indexes', [])
        variants = offer_details.get('variants', [])
        variant_options_by_image = {
            image_index: variants[index]['options']
            for index, image_index in enumerate(image_indexes)
            if image_index is not None
        }
        for index, image in enumerate(images):
            CatalogProductImage.objects.create(
                catalog_product=product,
                image=image,
                position=index,
                variant_options=variant_options_by_image.get(index, {}),
            )
        return product

    def update(self, instance, validated_data):
        offer_details = validated_data.pop('offer_details', None)
        images = validated_data.pop('images', [])
        if offer_details is not None:
            instance.request_offer_details = offer_details
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        image_indexes = (offer_details or {}).get('variant_image_indexes', [])
        variants = (offer_details or {}).get('variants', [])
        variant_options_by_image = {
            image_index: variants[index]['options']
            for index, image_index in enumerate(image_indexes)
            if image_index is not None and index < len(variants)
        }
        current_position = instance.request_images.count()
        for offset, image in enumerate(images):
            position = current_position + offset
            CatalogProductImage.objects.create(
                catalog_product=instance,
                image=image,
                position=position,
                variant_options=variant_options_by_image.get(offset, {}),
            )
        return instance


class CatalogOfferRequestSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    original_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True,
    )
    delivery_fee = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False, default=0,
    )
    stock = serializers.IntegerField(min_value=0, required=False, default=0)
    trader_sku = serializers.CharField(max_length=100, allow_blank=True, required=False, default='')
    condition = serializers.ChoiceField(choices=Product.CONDITION_CHOICES, default='new')
    availability = serializers.ChoiceField(
        choices=(
            ('in_stock', 'In stock'),
            ('preorder', 'Pre-order'),
            ('made_to_order', 'Made to order'),
            ('unavailable', 'Unavailable'),
        ),
        default='in_stock',
    )
    warranty = serializers.CharField(max_length=255, allow_blank=True, required=False, default='')
    delivery_options = serializers.ListField(
        child=serializers.CharField(max_length=120, allow_blank=False),
        required=False,
        default=list,
    )
    package_details = serializers.CharField(allow_blank=True, required=False, default='')
    variants = ProductVariantSerializer(many=True, required=False, default=list)
    variant_image_indexes = serializers.ListField(
        child=serializers.IntegerField(min_value=0, allow_null=True),
        required=False,
        default=list,
    )

    def validate(self, attrs):
        price = attrs['price']
        if price <= 0:
            raise serializers.ValidationError({'price': 'Price must be greater than zero.'})
        original_price = attrs.get('original_price')
        if original_price is not None and original_price < price:
            raise serializers.ValidationError({
                'original_price': 'Original price must be greater than or equal to price.',
            })
        return attrs


def _catalog_request_data(product, include_owner=False):
    images = []
    for image in product.request_images.all():
        images.append({
            'id': image.pk,
            'url': image.image.url if image.image else None,
            'variant_options': image.variant_options,
        })
    data = {
        'id': product.pk,
        'name': product.name,
        'brand': product.brand,
        'model': product.model,
        'product_type': product.product_type,
        'category_id': product.category_id,
        'category_name': product.category.name if product.category_id else None,
        'short_description': product.short_description,
        'long_description': product.long_description,
        'tags': product.tags,
        'specifications': product.specifications,
        'attributes': product.attributes,
        'identifiers': product.identifiers,
        'variant_options': product.get_variant_options(),
        'variants': [
            {
                'options': variant.options,
                'image_references': variant.image_references,
            }
            for variant in product.variants.all()
            if variant.is_active
        ],
        'image_references': product.image_references,
        'request_offer_details': product.request_offer_details,
        'images': images,
        'review_status': product.review_status,
        'review_note': product.review_note,
        'created_at': product.created_at,
    }
    if include_owner:
        data['requester_email'] = product.created_by.email if product.created_by_id else ''
        data['requester_name'] = getattr(product.created_by, 'name', '') if product.created_by_id else ''
    return data


def _create_initial_trader_offer(product):
    if not product.created_by_id:
        return None

    trader = TraderApplication.objects.filter(
        Q(user_id=product.created_by_id)
        | Q(email__iexact=product.created_by.email),
        status='approved',
    ).filter(
        Q(agreement_required=False) | Q(agreement_signed_at__isnull=False),
    ).order_by('-created_at').first()
    if not trader or TraderProduct.objects.filter(
        trader=trader,
        catalog_product=product,
    ).exists():
        return None

    serializer = CatalogOfferRequestSerializer(data=product.request_offer_details)
    serializer.is_valid(raise_exception=True)
    offer_details = dict(serializer.validated_data)
    variants = offer_details.pop('variants', [])
    offer_details.pop('variant_image_indexes', None)
    offer = TraderProduct.objects.create(
        trader=trader,
        catalog_product=product,
        listing_product=product.public_product,
        name=product.name,
        short_description=product.short_description,
        long_description=product.long_description,
        description=product.long_description,
        brand=product.brand,
        category=product.category,
        tags=product.tags,
        specifications=product.specifications,
        catalog_image_references=list(product.image_references or []),
        review_status='approved',
        is_active=True,
        **offer_details,
    )
    created_variants = []
    for data in variants:
        variant_data = dict(data)
        catalog_variant = CatalogVariant.objects.filter(
            catalog_product=product,
            options_key=CatalogVariant.make_options_key(variant_data['options']),
        ).first()
        variant_data.pop('image', None)
        created_variants.append(ProductVariant.objects.create(
            trader_product=offer,
            catalog_variant=catalog_variant,
            **variant_data,
        ))
    if created_variants:
        offer.price = min(variant.price for variant in created_variants)
        offer.stock = sum(variant.stock for variant in created_variants)
        offer.save(update_fields=('price', 'stock', 'updated_at'))
    return offer


@transaction.atomic
def _approve_catalog_request(product):
    references = list(product.image_references or [])
    for image in product.request_images.all():
        reference = getattr(image.image, 'public_id', None) or str(image.image)
        if reference and reference not in references:
            references.append(reference)
        options = image.variant_options if isinstance(image.variant_options, dict) else {}
        if options:
            options_key = CatalogVariant.make_options_key(options)
            variant, created = CatalogVariant.objects.get_or_create(
                catalog_product=product,
                options_key=options_key,
                defaults={
                    'options': options,
                    'image_references': [reference] if reference else [],
                },
            )
            if not created and reference and reference not in variant.image_references:
                variant.image_references = [*(variant.image_references or []), reference]
                variant.save(update_fields=('image_references',))

    offer_details = product.request_offer_details if isinstance(product.request_offer_details, dict) else {}
    variants = offer_details.get('variants', [])
    variant_options = [
        variant['options']
        for variant in variants
        if isinstance(variant, dict) and isinstance(variant.get('options'), dict)
    ]
    if not variant_options:
        variant_options = product.variant_options or []
    for position, options in enumerate(variant_options):
        if not isinstance(options, dict) or not options:
            continue
        options_key = CatalogVariant.make_options_key(options)
        CatalogVariant.objects.get_or_create(
            catalog_product=product,
            options_key=options_key,
            defaults={'options': options, 'position': position},
        )

    product.image_references = references
    product.variant_options = variant_options
    product.review_status = 'approved'
    product.is_active = True
    product.review_note = ''
    product.save(update_fields=(
        'image_references', 'variant_options', 'review_status', 'is_active', 'review_note', 'updated_at',
    ))
    from .catalog_sync import ensure_catalog_public_product

    ensure_catalog_public_product(product)
    _create_initial_trader_offer(product)


class CatalogProductView(APIView):
    """Public search and trader-submitted, admin-reviewed catalog requests."""

    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        if len(query) < 2:
            return Response([])

        query_key = _normalized(query)
        query_tokens = set(query_key.split())
        matches = []
        products = CatalogProduct.objects.filter(
            review_status='approved', is_active=True,
        ).select_related('category').prefetch_related('variants').order_by('name', 'pk')
        for product in products.iterator(chunk_size=200):
            fields = [
                product.name, product.brand, product.model, product.product_type,
                product.short_description, product.long_description,
                product.category.name if product.category_id else '',
                *_identifier_values(product.identifiers),
            ]
            searchable = [_normalized(value) for value in fields]
            searchable = [value for value in searchable if value]
            product_tokens = set(' '.join(searchable).split())
            if any(query_key in value for value in searchable) or (
                query_tokens and query_tokens.issubset(product_tokens)
            ):
                matches.append(product)
                if len(matches) == 50:
                    break
        return Response(CatalogProductSerializer(matches, many=True).data)

    def post(self, request):
        trader = TraderApplication.objects.filter(
            Q(user=request.user) | Q(email__iexact=request.user.email),
            status='approved',
        ).filter(
            Q(agreement_required=False) | Q(agreement_signed_at__isnull=False),
        ).order_by('-created_at').first()
        if not trader:
            return Response(
                {'detail': 'An approved trader account is required to request a catalog product.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CatalogProductRequestSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        matches = _find_similar_products(data)
        if matches:
            return Response(
                {
                    'detail': 'Similar catalog products already exist. Review them before requesting another product.',
                    'matches': [_candidate_data(product) for product in matches],
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                product = serializer.save()
        except IntegrityError:
            matches = _find_similar_products(data)
            return Response(
                {
                    'detail': 'A catalog product with the same brand/model identity already exists.',
                    'matches': [_candidate_data(item) for item in matches],
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                'id': product.pk,
                'name': product.name,
                'review_status': product.review_status,
                'detail': 'Product request submitted for catalog review.',
            },
            status=status.HTTP_201_CREATED,
        )


class CatalogProductBrowseView(APIView):
    """Paginated view of approved catalog products available to traders."""

    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        products = CatalogProduct.objects.filter(
            review_status='approved',
            is_active=True,
        ).select_related('category').prefetch_related('variants').order_by('-updated_at', '-pk')
        paginator = ProductPagination()
        page = paginator.paginate_queryset(products, request, view=self)
        serializer = CatalogProductSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class CatalogProductRequestsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        products = CatalogProduct.objects.filter(
            created_by=request.user,
        ).select_related('category').prefetch_related('request_images', 'variants').order_by('-created_at')
        return Response([_catalog_request_data(product) for product in products])


class AdminCatalogProductRequestsView(APIView):
    permission_classes = (permissions.IsAdminUser,)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request):
        products = CatalogProduct.objects.filter(
            created_by__isnull=False,
        ).select_related('category', 'created_by').prefetch_related(
            'request_images', 'variants',
        ).order_by('review_status', '-created_at')
        review_status = request.query_params.get('status')
        if review_status:
            products = products.filter(review_status=review_status)
        return Response([
            _catalog_request_data(product, include_owner=True)
            for product in products
        ])

    def patch(self, request, pk):
        product = get_object_or_404(
            CatalogProduct.objects.select_related('category', 'created_by').prefetch_related(
                'request_images', 'variants',
            ),
            pk=pk,
            created_by__isnull=False,
        )
        decision = request.data.get('review_status')
        review_note = request.data.get('review_note', '')
        allowed_statuses = {'approved', 'rejected', 'changes_required'}
        if decision not in (None, '') and (
            not isinstance(decision, str) or decision not in allowed_statuses
        ):
            return Response(
                {'review_status': 'Choose approved, rejected, or changes_required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(review_note, str):
            return Response(
                {'review_note': 'Review note must be text.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        review_note = review_note.strip()
        if decision in {'rejected', 'changes_required'} and not review_note:
            return Response(
                {'review_note': 'Provide a reason for this decision.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        editable_fields = set(CatalogProductRequestSerializer.Meta.fields) - {
            'offer_details', 'images',
        }
        edit_data = {
            key: value for key, value in request.data.items()
            if key in editable_fields or key in {'offer_details', 'images'}
        }
        if edit_data:
            serializer = CatalogProductRequestSerializer(
                product,
                data=edit_data,
                partial=True,
                context={'request': request},
            )
            serializer.is_valid(raise_exception=True)
            product = serializer.save()

        if decision == 'approved':
            offer_serializer = CatalogOfferRequestSerializer(data=product.request_offer_details)
            if not offer_serializer.is_valid():
                return Response(
                    {'offer_details': offer_serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            _approve_catalog_request(product)
        elif decision:
            product.review_status = decision
            product.review_note = review_note
            product.is_active = False
            product.save(update_fields=('review_status', 'review_note', 'is_active', 'updated_at'))
        elif edit_data:
            product.review_status = 'pending_review'
            product.is_active = False
            product.save(update_fields=('review_status', 'is_active', 'updated_at'))

        return Response(_catalog_request_data(product, include_owner=True))


class CatalogProductOffersView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request, pk):
        catalog_product = CatalogProduct.objects.filter(
            pk=pk, review_status='approved', is_active=True,
        ).first()
        if not catalog_product:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        from traders.models import TraderProduct

        offers = TraderProduct.objects.filter(
            catalog_product=catalog_product,
            is_active=True,
            review_status='approved',
            stock__gt=0,
            trader__status='approved',
            trader__is_visible=True,
            trader__is_closed=False,
        ).select_related(
            'trader', 'catalog_product__category', 'listing_product__category',
            'listing_product__catalog_product__category', 'legacy_public_product__category',
        ).prefetch_related(
            'variants', 'listing_product__images', 'listing_product__variants',
            'legacy_public_product__images', 'legacy_public_product__variants',
        ).order_by('price', 'pk')
        data = []
        for offer in offers:
            public_product = offer.listing_product or offer.public_product
            if public_product:
                data.append(ProductSerializer(
                    public_product,
                    context={'request': request, 'trader_offer': offer},
                ).data)
        public_product = catalog_product.public_product
        if public_product and public_product.price > 0 and public_product.stock > 0:
            data.append(ProductSerializer(
                public_product,
                context={'request': request, 'direct_catalog_offer': True},
            ).data)
        data.sort(key=lambda item: (Decimal(item['listed_price']), item['id']))
        return Response(data)
