import hashlib
import json
import re

from django.db import migrations


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


def _normalize_identity(value):
    return ' '.join(re.findall(r'[a-z0-9]+', str(value or '').casefold()))


def _image_reference(value):
    if not value:
        return None
    reference = str(value).strip()
    return reference or None


def _identity_key(name, brand, model, identifiers):
    for key in ('gtin', 'barcode', 'ean', 'isbn', 'mpn', 'manufacturer_part_number'):
        value = _normalize_identity(identifiers.get(key))
        if value:
            return f'{key}|{value}'[:255]
    model_key = _normalize_identity(model) or _normalize_identity(name)
    return f'{_normalize_identity(brand)}|{model_key}'[:255]


def link_products_to_shared_catalog(apps, schema_editor):
    CatalogProduct = apps.get_model('products', 'CatalogProduct')
    CatalogVariant = apps.get_model('products', 'CatalogVariant')
    Product = apps.get_model('products', 'Product')
    ProductVariant = apps.get_model('products', 'ProductVariant')
    TraderProduct = apps.get_model('traders', 'TraderProduct')

    products = Product.objects.filter(catalog_product__isnull=True).select_related(
        'trader', 'trader_product__trader',
    ).prefetch_related('images', 'variants')

    for product in products.iterator(chunk_size=200):
        specifications = product.specifications if isinstance(product.specifications, dict) else {}
        normalized_specifications = {
            str(key).strip().casefold().replace(' ', '_'): value
            for key, value in specifications.items()
        }
        model = ''
        identifiers = {}
        for source_key, target_key in IDENTIFIER_KEYS.items():
            value = normalized_specifications.get(source_key)
            if value in (None, ''):
                continue
            if target_key == 'model' and not model:
                model = str(value).strip()
            elif target_key != 'model':
                identifiers[target_key] = value
        if model:
            identifiers.setdefault('model', model)

        identity_key = _identity_key(product.name, product.brand, model, identifiers)
        catalog_product = CatalogProduct.objects.filter(identity_key=identity_key).first()
        image_references = []
        for value in [product.image, *(image.image for image in product.images.all())]:
            reference = _image_reference(value)
            if reference and reference not in image_references:
                image_references.append(reference)

        variants = list(product.variants.all())
        variant_options = []
        for variant in variants:
            options = variant.options if isinstance(variant.options, dict) else {}
            if options and options not in variant_options:
                variant_options.append(options)
            reference = _image_reference(variant.image)
            if reference and reference not in image_references:
                image_references.append(reference)

        source_review_status = product.review_status
        review_status = {
            'approved': 'approved',
            'rejected': 'rejected',
            'disabled': 'disabled',
            'archived': 'disabled',
            'changes_required': 'changes_required',
        }.get(source_review_status, 'pending_review')

        if catalog_product is None:
            source_trader = product.trader
            if source_trader is None and product.trader_product_id:
                source_trader = product.trader_product.trader
            catalog_product = CatalogProduct.objects.create(
                name=product.name,
                brand=product.brand,
                model=model,
                product_type=str(normalized_specifications.get('product_type', '') or ''),
                category_id=product.category_id,
                short_description=product.short_description,
                long_description=product.long_description,
                tags=product.tags if isinstance(product.tags, list) else [],
                specifications=specifications,
                attributes=specifications,
                identifiers=identifiers,
                variant_options=variant_options,
                image_references=image_references,
                review_status=review_status,
                review_note=product.review_note,
                is_active=product.is_active and review_status == 'approved',
                created_by_id=source_trader.user_id if source_trader else None,
            )
        else:
            merged_images = list(catalog_product.image_references or [])
            for reference in image_references:
                if reference not in merged_images:
                    merged_images.append(reference)
            merged_options = list(catalog_product.variant_options or [])
            for options in variant_options:
                if options not in merged_options:
                    merged_options.append(options)
            update_fields = []
            if merged_images != catalog_product.image_references:
                catalog_product.image_references = merged_images
                update_fields.append('image_references')
            if merged_options != catalog_product.variant_options:
                catalog_product.variant_options = merged_options
                update_fields.append('variant_options')
            if (
                product.is_active
                and review_status == 'approved'
                and catalog_product.review_status in {'pending_review', 'changes_required'}
            ):
                catalog_product.review_status = 'approved'
                catalog_product.review_note = ''
                catalog_product.is_active = True
                update_fields.extend(('review_status', 'review_note', 'is_active'))
            if update_fields:
                catalog_product.save(update_fields=tuple(dict.fromkeys(update_fields)))

        Product.objects.filter(pk=product.pk).update(catalog_product_id=catalog_product.pk)

        for variant in variants:
            options = variant.options if isinstance(variant.options, dict) else {}
            if not options:
                continue
            options_key = hashlib.sha256(
                json.dumps(options, sort_keys=True, separators=(',', ':')).encode('utf-8')
            ).hexdigest()
            catalog_variant, created = CatalogVariant.objects.get_or_create(
                catalog_product_id=catalog_product.pk,
                options_key=options_key,
                defaults={
                    'options': options,
                    'image_references': (
                        [reference] if (reference := _image_reference(variant.image)) else []
                    ),
                    'is_active': variant.is_active,
                },
            )
            if not created:
                reference = _image_reference(variant.image)
                existing_references = list(catalog_variant.image_references or [])
                if reference and reference not in existing_references:
                    catalog_variant.image_references = [*existing_references, reference]
                    catalog_variant.save(update_fields=('image_references',))
            ProductVariant.objects.filter(pk=variant.pk).update(catalog_variant_id=catalog_variant.pk)

        if product.trader_product_id:
            TraderProduct.objects.filter(
                pk=product.trader_product_id,
                catalog_product_id__isnull=True,
            ).update(
                catalog_product_id=catalog_product.pk,
                catalog_image_references=image_references,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0026_catalogproduct_request_offer_details_and_more'),
        ('traders', '0017_backfill_catalog_from_products'),
    ]

    operations = [
        migrations.RunPython(link_products_to_shared_catalog, migrations.RunPython.noop),
    ]
