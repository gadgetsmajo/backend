import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation

from django.db import migrations
from django.db.models import Q
from django.utils.text import slugify


def backfill_approved_catalog_request_offers(apps, schema_editor):
    CatalogProduct = apps.get_model('products', 'CatalogProduct')
    CatalogVariant = apps.get_model('products', 'CatalogVariant')
    Product = apps.get_model('products', 'Product')
    ProductVariant = apps.get_model('products', 'ProductVariant')
    TraderApplication = apps.get_model('traders', 'TraderApplication')
    TraderProduct = apps.get_model('traders', 'TraderProduct')
    database = schema_editor.connection.alias

    requests = CatalogProduct.objects.using(database).filter(
        created_by__isnull=False,
        review_status='approved',
        is_active=True,
    ).select_related('created_by').iterator()
    for catalog in requests:
        details = catalog.request_offer_details
        if not isinstance(details, dict):
            continue
        try:
            price = Decimal(str(details.get('price', '0')))
            stock = int(details.get('stock', 0))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not price.is_finite() or price <= 0 or stock < 0:
            continue

        trader = TraderApplication.objects.using(database).filter(
            Q(user_id=catalog.created_by_id)
            | Q(email__iexact=catalog.created_by.email),
            status='approved',
        ).filter(
            Q(agreement_required=False) | Q(agreement_signed_at__isnull=False),
        ).order_by('-created_at').first()
        if not trader or TraderProduct.objects.using(database).filter(
            trader_id=trader.pk,
            catalog_product_id=catalog.pk,
        ).exists():
            continue

        anchor = (
            Product.objects.using(database).filter(pk=catalog.public_product_id).first()
            if catalog.public_product_id else None
        )
        if anchor is None:
            anchor = Product.objects.using(database).filter(
                catalog_product_id=catalog.pk,
                trader_id__isnull=True,
                trader_product_id__isnull=True,
            ).order_by('pk').first()
        if anchor is None:
            product_uuid = uuid.uuid4()
            anchor = Product.objects.using(database).create(
                uuid=product_uuid,
                name=catalog.name,
                slug=f'{slugify(catalog.name) or "product"}-{product_uuid.hex[:12]}',
                category_id=catalog.category_id,
                brand=catalog.brand,
                tags=catalog.tags,
                specifications=catalog.specifications,
                short_description=catalog.short_description,
                long_description=catalog.long_description,
                image=(catalog.image_references or [None])[0],
                price=0,
                stock=0,
                catalog_product_id=catalog.pk,
                is_active=True,
                review_status='approved',
                is_catalog_anchor=True,
            )
        if catalog.public_product_id != anchor.pk:
            CatalogProduct.objects.using(database).filter(pk=catalog.pk).update(
                public_product_id=anchor.pk,
            )

        variant_data = details.get('variants', [])
        if not isinstance(variant_data, list):
            continue
        parsed_variants = []
        for variant in variant_data:
            if not isinstance(variant, dict) or not isinstance(variant.get('options'), dict):
                parsed_variants = None
                break
            try:
                variant_price = Decimal(str(variant.get('price', price)))
                variant_stock = int(variant.get('stock', 0))
            except (InvalidOperation, TypeError, ValueError):
                parsed_variants = None
                break
            if not variant_price.is_finite() or variant_price <= 0 or variant_stock < 0:
                parsed_variants = None
                break
            parsed_variants.append((variant, variant_price, variant_stock))
        if parsed_variants is None:
            continue

        offer_price = min((entry[1] for entry in parsed_variants), default=price)
        offer_stock = sum(entry[2] for entry in parsed_variants) if parsed_variants else stock
        offer = TraderProduct.objects.using(database).create(
            trader_id=trader.pk,
            catalog_product_id=catalog.pk,
            listing_product_id=anchor.pk,
            trader_sku=details.get('trader_sku', ''),
            catalog_image_references=catalog.image_references or [],
            name=catalog.name,
            short_description=catalog.short_description,
            long_description=catalog.long_description,
            description=catalog.long_description,
            brand=catalog.brand,
            condition=details.get('condition', 'new'),
            availability=details.get('availability', 'in_stock'),
            warranty=details.get('warranty', ''),
            delivery_options=details.get('delivery_options', []),
            package_details=details.get('package_details', ''),
            tags=catalog.tags,
            specifications=catalog.specifications,
            price=offer_price,
            original_price=details.get('original_price'),
            delivery_fee=details.get('delivery_fee', 0),
            stock=offer_stock,
            category_id=catalog.category_id,
            is_active=True,
            review_status='approved',
        )
        for variant, variant_price, variant_stock in parsed_variants:
            options = variant['options']
            options_key = hashlib.sha256(
                json.dumps(options, sort_keys=True, separators=(',', ':')).encode('utf-8')
            ).hexdigest()
            catalog_variant = CatalogVariant.objects.using(database).filter(
                catalog_product_id=catalog.pk,
                options_key=options_key,
            ).first()
            ProductVariant.objects.using(database).create(
                trader_product_id=offer.pk,
                catalog_variant_id=catalog_variant.pk if catalog_variant else None,
                sku=variant.get('sku', ''),
                options=options,
                price=variant_price,
                compare_at_price=variant.get('compare_at_price'),
                stock=variant_stock,
                weight=variant.get('weight'),
                is_active=variant.get('is_active', True),
            )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0028_catalogproduct_public_product_and_more'),
        ('traders', '0019_traderproduct_listing_product_and_more'),
    ]

    operations = [
        migrations.RunPython(
            backfill_approved_catalog_request_offers,
            migrations.RunPython.noop,
        ),
    ]
