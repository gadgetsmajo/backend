import json
import re
from difflib import SequenceMatcher

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CatalogProduct, CatalogVariant, Category, Product, ProductVariant
from .serializers import ProductSerializer
from .visibility import public_marketplace_product_filter
from traders.models import TraderApplication


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

    TraderProduct.objects.filter(catalog_product_id__in=source_pk_list).update(
        catalog_product_id=survivor.pk,
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

    class Meta:
        model = CatalogProduct
        fields = (
            'name', 'brand', 'model', 'product_type', 'category_id',
            'short_description', 'long_description', 'tags', 'specifications',
            'attributes', 'identifiers', 'variant_options',
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
        return attrs


class CatalogProductView(APIView):
    """Public search and trader-submitted, admin-reviewed catalog requests."""

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

        serializer = CatalogProductRequestSerializer(data=request.data)
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
                product = serializer.save(
                    created_by=request.user,
                    review_status='pending_review',
                    is_active=False,
                )
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


class CatalogProductOffersView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request, pk):
        catalog_product = CatalogProduct.objects.filter(
            pk=pk, review_status='approved', is_active=True,
        ).first()
        if not catalog_product:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        offers = Product.objects.filter(
            catalog_product=catalog_product,
            is_active=True,
            review_status='approved',
        ).filter(public_marketplace_product_filter()).select_related(
            'category', 'trader', 'trader_product',
            'catalog_product__category', 'trader_product__catalog_product',
        ).prefetch_related(
            'variants', 'images',
        ).order_by('price', 'pk')
        return Response(ProductSerializer(offers, many=True, context={'request': request}).data)
