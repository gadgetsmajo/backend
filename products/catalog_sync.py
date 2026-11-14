import hashlib
import json

from django.db import transaction

from .models import CatalogProduct, CatalogVariant, Product, ProductVariant
from traders.models import TraderProduct


IDENTIFIER_KEYS = {
    'barcode': 'barcode',
    'ean': 'ean',
    'gtin': 'gtin',
    'isbn': 'isbn',
    'mpn': 'mpn',
    'manufacturer_part_number': 'mpn',
    'model_number': 'model',
    'model': 'model',
}


def _image_reference(value):
    if not value:
        return None
    reference = str(value).strip()
    return reference or None


def _product_catalog_metadata(product):
    specifications = product.specifications if isinstance(product.specifications, dict) else {}
    normalized = {
        str(key).strip().casefold().replace(' ', '_'): value
        for key, value in specifications.items()
    }
    model = ''
    identifiers = {}
    for source_key, target_key in IDENTIFIER_KEYS.items():
        value = normalized.get(source_key)
        if value in (None, ''):
            continue
        if target_key == 'model' and not model:
            model = str(value).strip()
        elif target_key != 'model':
            identifiers[target_key] = value
    if model:
        identifiers.setdefault('model', model)

    return {
        'name': product.name,
        'brand': product.brand,
        'model': model,
        'product_type': str(normalized.get('product_type', '') or ''),
        'category': product.category,
        'short_description': product.short_description,
        'long_description': product.long_description,
        'tags': product.tags if isinstance(product.tags, list) else [],
        'specifications': specifications,
        'attributes': specifications,
        'identifiers': identifiers,
    }


def _merge_reference(references, value):
    reference = _image_reference(value)
    if reference and reference not in references:
        references.append(reference)


def _sync_catalog_media(product, catalog_product):
    image_references = list(catalog_product.image_references or [])
    _merge_reference(image_references, product.image)
    for image in product.images.all():
        _merge_reference(image_references, image.image)

    for variant in product.variants.all():
        options = variant.options if isinstance(variant.options, dict) else {}
        _merge_reference(image_references, variant.image)
        if not options:
            continue

        options_key = hashlib.sha256(
            json.dumps(options, sort_keys=True, separators=(',', ':')).encode('utf-8')
        ).hexdigest()
        catalog_variant, _ = CatalogVariant.objects.get_or_create(
            catalog_product=catalog_product,
            options_key=options_key,
            defaults={
                'options': options,
                'image_references': (
                    [str(variant.image).strip()] if _image_reference(variant.image) else []
                ),
                'is_active': variant.is_active,
            },
        )
        variant_references = list(catalog_variant.image_references or [])
        _merge_reference(variant_references, variant.image)
        catalog_variant.image_references = variant_references
        catalog_variant.is_active = catalog_variant.is_active or variant.is_active
        catalog_variant.save(update_fields=('image_references', 'is_active'))
        if variant.catalog_variant_id != catalog_variant.pk:
            ProductVariant.objects.filter(pk=variant.pk).update(catalog_variant_id=catalog_variant.pk)

    catalog_product.image_references = image_references
    catalog_product.variant_options = [
        variant.options for variant in catalog_product.variants.filter(is_active=True)
    ]
    catalog_product.save(update_fields=('image_references', 'variant_options', 'updated_at'))


@transaction.atomic
def ensure_catalog_public_product(catalog_product):
    if catalog_product.public_product_id:
        product = catalog_product.public_product
        updates = []
        if not product.is_catalog_anchor:
            product.is_catalog_anchor = True
            updates.append('is_catalog_anchor')
        if product.is_active != catalog_product.is_active:
            product.is_active = catalog_product.is_active
            updates.append('is_active')
        if product.review_status != catalog_product.review_status:
            product.review_status = catalog_product.review_status
            updates.append('review_status')
        if updates:
            product.save(update_fields=updates)
        return product

    product = Product.objects.filter(
        catalog_product=catalog_product,
        trader__isnull=True,
        trader_product__isnull=True,
    ).order_by('pk').first()
    if product is None:
        references = catalog_product.image_references or []
        product = Product.objects.create(
            name=catalog_product.name,
            brand=catalog_product.brand,
            category=catalog_product.category,
            tags=catalog_product.tags,
            specifications=catalog_product.specifications,
            short_description=catalog_product.short_description,
            long_description=catalog_product.long_description,
            image=references[0] if references else None,
            price=0,
            stock=0,
            catalog_product=catalog_product,
            is_active=catalog_product.is_active,
            review_status=catalog_product.review_status,
            is_catalog_anchor=True,
        )
    else:
        product.is_catalog_anchor = True
        product.is_active = catalog_product.is_active
        product.review_status = catalog_product.review_status
        product.save(update_fields=('is_catalog_anchor', 'is_active', 'review_status'))

    catalog_product.public_product = product
    catalog_product.save(update_fields=('public_product', 'updated_at'))
    return product


@transaction.atomic
def sync_product_to_catalog(product, *, approve_existing=False):
    """Make an approved public Product discoverable through the shared catalog."""
    catalog_product = product.catalog_product if product.catalog_product_id else None
    if catalog_product is None and product.trader_product_id:
        catalog_product = product.trader_product.catalog_product

    metadata = _product_catalog_metadata(product)
    if catalog_product is None:
        identity_key = CatalogProduct.make_identity_key(
            metadata['name'],
            metadata['brand'],
            metadata['model'],
            metadata['identifiers'],
        )
        catalog_product = CatalogProduct.objects.select_for_update().filter(
            identity_key=identity_key,
        ).first()

    is_new = catalog_product is None
    source_status = {
        'approved': 'approved',
        'rejected': 'rejected',
        'changes_required': 'changes_required',
        'disabled': 'disabled',
        'archived': 'disabled',
    }.get(product.review_status, 'pending_review')

    if is_new:
        catalog_product = CatalogProduct.objects.create(
            **metadata,
            variant_options=[],
            image_references=[],
            review_status=source_status,
            review_note=product.review_note,
            is_active=product.is_active and source_status == 'approved',
        )

    is_catalog_owner = product.trader_id is None and product.trader_product_id is None
    if not is_new and is_catalog_owner:
        for field, value in metadata.items():
            setattr(catalog_product, field, value)
        catalog_product.review_status = source_status
        catalog_product.review_note = product.review_note
        catalog_product.is_active = product.is_active and source_status == 'approved'
        catalog_product.save()
    elif (
        not is_new
        and approve_existing
        and product.is_active
        and source_status == 'approved'
        and catalog_product.review_status in {'pending_review', 'changes_required'}
    ):
        catalog_product.review_status = 'approved'
        catalog_product.review_note = ''
        catalog_product.is_active = True
        catalog_product.save(update_fields=('review_status', 'review_note', 'is_active', 'updated_at'))

    if product.catalog_product_id != catalog_product.pk:
        Product.objects.filter(pk=product.pk).update(catalog_product_id=catalog_product.pk)
        product.catalog_product = catalog_product
    if is_catalog_owner and not catalog_product.public_product_id:
        product.is_catalog_anchor = True
        product.save(update_fields=('is_catalog_anchor',))
        catalog_product.public_product = product
        catalog_product.save(update_fields=('public_product', 'updated_at'))
    elif catalog_product.public_product_id == product.pk and not product.is_catalog_anchor:
        product.is_catalog_anchor = True
        product.save(update_fields=('is_catalog_anchor',))
    if product.trader_product_id:
        TraderProduct.objects.filter(
            pk=product.trader_product_id,
            catalog_product_id__isnull=True,
        ).update(catalog_product_id=catalog_product.pk)

    if is_new or is_catalog_owner:
        _sync_catalog_media(product, catalog_product)

    return catalog_product
