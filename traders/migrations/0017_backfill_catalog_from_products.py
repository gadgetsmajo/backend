import json
import hashlib

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


def _image_reference(value):
    if not value:
        return None
    reference = str(value).strip()
    return reference or None


def backfill_catalog_from_products(apps, schema_editor):
    CatalogProduct = apps.get_model('products', 'CatalogProduct')
    Product = apps.get_model('products', 'Product')
    ProductVariant = apps.get_model('products', 'ProductVariant')
    CatalogVariant = apps.get_model('products', 'CatalogVariant')
    TraderProduct = apps.get_model('traders', 'TraderProduct')

    products = Product.objects.select_related(
        'catalog_product', 'trader', 'trader_product__trader',
    ).prefetch_related('images', 'variants')

    for product in products.iterator(chunk_size=200):
        catalog_product = product.catalog_product
        image_references = []
        for value in [product.image]:
            reference = _image_reference(value)
            if reference and reference not in image_references:
                image_references.append(reference)
        for image in product.images.all():
            reference = _image_reference(image.image)
            if reference and reference not in image_references:
                image_references.append(reference)

        variants = list(product.variants.all())
        variant_options = []
        seen_options = set()
        for variant in variants:
            options = variant.options if isinstance(variant.options, dict) else {}
            option_key = json.dumps(options, sort_keys=True, separators=(',', ':'))
            if options and option_key not in seen_options:
                seen_options.add(option_key)
                variant_options.append(options)
            reference = _image_reference(variant.image)
            if reference and reference not in image_references:
                image_references.append(reference)

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

        if catalog_product is None:
            source_trader = product.trader
            if source_trader is None and product.trader_product_id:
                source_trader = product.trader_product.trader

            source_review_status = product.review_status
            review_status = {
                'approved': 'approved',
                'rejected': 'rejected',
                'disabled': 'disabled',
                'archived': 'disabled',
            }.get(source_review_status, 'pending_review')
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
            Product.objects.filter(pk=product.pk).update(catalog_product_id=catalog_product.pk)

        for variant in variants:
            options = variant.options if isinstance(variant.options, dict) else {}
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
                existing_references = catalog_variant.image_references or []
                if reference and reference not in existing_references:
                    CatalogVariant.objects.filter(pk=catalog_variant.pk).update(
                        image_references=[*existing_references, reference],
                    )
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
        ('products', '0025_catalogvariant_and_more'),
        ('traders', '0016_traderproduct_catalog_image_references_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_catalog_from_products, migrations.RunPython.noop),
    ]
