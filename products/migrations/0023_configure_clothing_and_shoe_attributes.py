from django.db import migrations


CLOTHING_ATTRIBUTES = (
    ('Product Type', 'product-type', 'text', [
        'T-Shirts', 'Shirts', 'Blouses', 'Polo Shirts', 'Sweaters', 'Hoodies', 'Jackets',
        'Coats', 'Dresses', 'Skirts', 'Trousers', 'Jeans', 'Shorts', 'Suits', 'Formal Wear',
        'Sportswear', 'Underwear', 'Sleepwear', 'Activewear', 'Traditional Wear',
        "Children's Clothing", 'Other',
    ], True, False, False),
    ('Gender', 'gender', 'dropdown', ['Men', 'Women', 'Unisex', 'Boys', 'Girls', 'Babies'], True, False, True),
    ('Material', 'material', 'multi_select', [
        'Cotton', 'Wool', 'Linen', 'Silk', 'Polyester', 'Nylon', 'Rayon', 'Viscose',
        'Acrylic', 'Denim', 'Leather', 'Suede', 'Velvet', 'Fleece', 'Chiffon', 'Satin',
        'Lace', 'Cashmere', 'Spandex / Elastane', 'Jersey', 'Canvas', 'Corduroy',
        'Flannel', 'Tweed', 'Polyester Blend', 'Cotton Blend', 'Wool Blend', 'Other',
    ], False, False, True),
    ('Material Composition', 'material-composition', 'text', [], False, False, False),
    ('Pattern', 'pattern', 'text', [
        'Plain', 'Striped', 'Checked', 'Floral', 'Printed', 'Polka Dot', 'Camouflage',
        'Geometric', 'Graphic', 'Animal Print', 'Textured', 'Embroidered', 'Other',
    ], False, False, True),
    ('Fit', 'fit', 'text', [
        'Regular Fit', 'Slim Fit', 'Loose Fit', 'Oversized', 'Relaxed Fit', 'Skinny Fit',
        'Straight Fit', 'Tailored Fit', 'Other',
    ], False, False, True),
    ('Care Instructions', 'care-instructions', 'text', [], False, False, False),
    ('Size System', 'size-system', 'text', ['International', 'US', 'UK', 'EU', 'Custom'], False, False, True),
    ('Color', 'color', 'color', [
        'Black', 'White', 'Grey', 'Red', 'Blue', 'Green', 'Yellow', 'Orange', 'Brown',
        'Beige', 'Pink', 'Purple', 'Navy', 'Maroon', 'Cream', 'Gold', 'Silver',
        'Multicolor', 'Other',
    ], True, True, True),
    ('Size', 'size', 'size', [
        'XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', '4XL', '5XL',
        '6', '8', '10', '12', '14', '16', '18', '20', '22', '24',
        '26', '28', '30', '32', '34', '36', '38', '40', '42', '44', '46', '48', '50',
        'Free Size', 'One Size', 'Custom', 'Other',
    ], True, True, True),
)

SHOE_ATTRIBUTES = (
    ('Product Type', 'product-type', 'text', [
        'Sneakers', 'Running Shoes', 'Sports Shoes', 'Formal Shoes', 'Casual Shoes',
        'Boots', 'Sandals', 'Slippers', 'Loafers', 'Heels', 'Flats', 'School Shoes',
        'Safety Shoes', 'Hiking Shoes', 'Football Boots', 'Other',
    ], True, False, False),
    ('Gender', 'gender', 'dropdown', ['Men', 'Women', 'Unisex', 'Boys', 'Girls', 'Kids'], True, False, True),
    ('Material', 'material', 'multi_select', [
        'Leather', 'Synthetic Leather', 'Genuine Leather', 'Suede', 'Canvas', 'Mesh',
        'Textile', 'Rubber', 'PVC', 'EVA', 'Polyester', 'Nylon', 'Cotton', 'Synthetic',
        'Other',
    ], False, False, True),
    ('Sole Material', 'sole-material', 'text', [
        'Rubber', 'EVA', 'PVC', 'TPR', 'PU', 'Leather', 'Synthetic', 'Other',
    ], False, False, True),
    ('Style', 'style', 'text', [], False, False, False),
    ('Intended Use', 'intended-use', 'text', [], False, False, False),
    ('Size System', 'size-system', 'text', ['EU', 'UK', 'US', 'Custom'], True, False, True),
    ('Color', 'color', 'color', [
        'Black', 'White', 'Grey', 'Red', 'Blue', 'Green', 'Brown', 'Beige', 'Navy',
        'Yellow', 'Pink', 'Purple', 'Orange', 'Multicolor', 'Other',
    ], True, True, True),
    ('Shoe Size', 'size', 'size', [
        '35', '36', '37', '38', '39', '40', '41', '42', '43', '44', '45', '46',
        '47', '48', '49', '50',
    ], True, True, True),
)


def _upsert_attributes(CategoryAttribute, database, category_id, rows):
    for position, (name, key, input_type, choices, required, is_variant, filterable) in enumerate(rows):
        CategoryAttribute.objects.using(database).update_or_create(
            category_id=category_id,
            key=key,
            defaults={
                'name': name,
                'input_type': input_type,
                'choices': choices,
                'is_required': required,
                'is_variant': is_variant,
                'is_filterable': filterable,
                'position': position,
            },
        )


def configure_fashion_attributes(apps, schema_editor):
    Category = apps.get_model('products', 'Category')
    CategoryAttribute = apps.get_model('products', 'CategoryAttribute')
    database = schema_editor.connection.alias

    clothing = Category.objects.using(database).filter(slug='clothing').first()
    if clothing and clothing.parent_id:
        _upsert_attributes(CategoryAttribute, database, clothing.pk, CLOTHING_ATTRIBUTES)

    shoe_root = Category.objects.using(database).filter(slug='shoes', parent__isnull=True).first()
    if not shoe_root:
        return

    category_ids = [shoe_root.pk]
    pending = [shoe_root.pk]
    while pending:
        child_ids = list(
            Category.objects.using(database)
            .filter(parent_id__in=pending)
            .values_list('pk', flat=True)
        )
        category_ids.extend(child_ids)
        pending = child_ids

    for category_id in category_ids:
        _upsert_attributes(CategoryAttribute, database, category_id, SHOE_ATTRIBUTES)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0022_repair_fashion_category_collision'),
    ]

    operations = [
        migrations.RunPython(configure_fashion_attributes, migrations.RunPython.noop),
    ]
