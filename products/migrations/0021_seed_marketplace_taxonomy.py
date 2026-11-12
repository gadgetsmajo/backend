import re
import unicodedata

from django.db import migrations
from django.utils.text import slugify


TAXONOMY = (
    ("Electronics", (
        ("Electronic Components", ()),
        ("Sensors", ()),
        ("Modules", ()),
        ("Development Boards", (("ESP32", ()),)),
        ("Power Supplies", ()),
        ("Cables & Connectors", ()),
        ("Batteries & Chargers", ()),
        ("Electronic Accessories", ()),
    )),
    ("Computers & Laptops", (
        ("Laptops", ()), ("Desktop Computers", ()), ("Monitors", ()), ("Keyboards", ()),
        ("Mice", ()), ("Printers", ()), ("Storage Devices", ()), ("Computer Components", ()),
        ("Networking", ()), ("Computer Accessories", ()),
    )),
    ("Phones & Tablets", (
        ("Smartphones", ()), ("Tablets", ()), ("Feature Phones", ()), ("Phone Cases", ()),
        ("Screen Protectors", ()), ("Chargers", ()), ("Power Banks", ()), ("Cables", ()),
        ("Earphones & Headsets", ()), ("Phone Accessories", ()),
    )),
    ("Fashion & Accessories", (
        ("Men's Fashion", ()), ("Women's Fashion", ()), ("Kids' Fashion", ()), ("Clothing", ()),
        ("Bags", ()), ("Handbags", ()), ("Backpacks", ()), ("Belts", ()), ("Wallets", ()),
        ("Sunglasses", ()), ("Hats & Caps", ()), ("Fashion Accessories", ()),
    )),
    ("Shoes", (
        ("Men's Shoes", ()), ("Women's Shoes", ()), ("Children's Shoes", ()), ("Sneakers", ()),
        ("Sports Shoes", ()), ("Sandals", ()), ("Boots", ()), ("Formal Shoes", ()), ("Slippers", ()),
    )),
    ("Home & Living", (
        ("Furniture", ()), ("Home Decor", ()), ("Bedding & Linen", ()), ("Curtains", ()),
        ("Storage & Organization", ()), ("Cleaning Supplies", ()), ("Bathroom", ()),
        ("Kitchen & Dining", ()), ("Lighting", ()), ("Home Accessories", ()),
    )),
    ("Home Appliances", (
        ("Refrigerators & Freezers", ()), ("Washing Machines", ()), ("Cookers & Ovens", ()),
        ("Microwaves", ()), ("Blenders & Mixers", ()), ("Electric Kettles", ()), ("Irons", ()),
        ("Fans", ()), ("Air Conditioners", ()), ("Vacuum Cleaners", ()), ("Small Appliances", ()),
    )),
    ("Beauty & Personal Care", (
        ("Skincare", ()), ("Hair Care", ()), ("Hair Accessories", ()), ("Makeup", ()),
        ("Fragrances", ()), ("Men's Grooming", ()), ("Oral Care", ()), ("Body Care", ()),
        ("Beauty Tools", ()), ("Personal Care Appliances", ()),
    )),
    ("Health & Wellness", (
        ("Fitness & Exercise", ()), ("First Aid", ()), ("Medical Supplies", ()),
        ("Health Monitoring", ()), ("Massage & Recovery", ()), ("Wellness Products", ()),
    )),
    ("Baby & Kids", (
        ("Baby Clothing", ()), ("Baby Shoes", ()), ("Baby Feeding", ()), ("Baby Care", ()),
        ("Diapers & Changing", ()), ("Baby Gear", ()), ("Maternity", ()), ("Kids Accessories", ()),
    )),
    ("Toys & Games", (
        ("Educational Toys", ()), ("Building Toys", ()), ("Dolls", ()), ("Remote-Controlled Toys", ()),
        ("Board Games", ()), ("Puzzles", ()), ("Outdoor Toys", ()), ("Kids Games", ()),
    )),
    ("Gaming", (
        ("Gaming Consoles", ()), ("Controllers", ()), ("Gaming Headsets", ()), ("Gaming Keyboards", ()),
        ("Gaming Mice", ()), ("Gaming Chairs", ()), ("Games", ()), ("Gaming Accessories", ()),
    )),
    ("Sports & Outdoors", (
        ("Football", ()), ("Basketball", ()), ("Volleyball", ()), ("Running", ()), ("Cycling", ()),
        ("Gym & Fitness", ()), ("Sportswear", ()), ("Camping", ()), ("Hiking", ()),
        ("Outdoor Equipment", ()),
    )),
    ("Tools & Hardware", (
        ("Hand Tools", ()), ("Power Tools", ()), ("Tool Sets", ()), ("Measuring Tools", ()),
        ("Electrical Tools", ()), ("Plumbing", ()), ("Hardware", ()), ("Workshop Equipment", ()),
        ("Safety Equipment", ()),
    )),
    ("Automotive", (
        ("Car Accessories", ()), ("Motorcycle Accessories", ()), ("Car Electronics", ()),
        ("Car Care", ()), ("Interior Accessories", ()), ("Exterior Accessories", ()), ("Spare Parts", ()),
        ("Tyres & Wheels", ()), ("Automotive Tools", ()),
    )),
    ("Agriculture & Farming", (
        ("Irrigation", ()), ("Water Pumps", ()), ("Farming Tools", ()), ("Seeds", ()),
        ("Gardening", ()), ("Greenhouse Supplies", ()), ("Sprayers", ()), ("Poultry Equipment", ()),
        ("Animal Equipment", ()), ("Agricultural Machinery", ()), ("Farm Supplies", ()),
    )),
    ("Office & Stationery", (
        ("Stationery", ()), ("Pens & Pencils", ()), ("Paper Products", ()), ("School Supplies", ()),
        ("Office Supplies", ()), ("Printers & Accessories", ()), ("Filing & Storage", ()),
        ("Office Furniture", ()), ("Packaging Materials", ()),
    )),
    ("Books & Education", (
        ("Textbooks", ()), ("Novels", ()), ("Children's Books", ()), ("Educational Materials", ()),
        ("Revision Books", ()), ("Study Guides", ()), ("Learning Kits", ()),
    )),
    ("Cameras & Photography", (
        ("Digital Cameras", ()), ("Action Cameras", ()), ("Lenses", ()), ("Tripods", ()),
        ("Camera Bags", ()), ("Memory Cards", ()), ("Camera Lighting", ()), ("Microphones", ()),
        ("Photography Accessories", ()),
    )),
    ("Smart Home & Security", (
        ("CCTV Cameras", ()), ("Smart Cameras", ()), ("Smart Locks", ()), ("Smart Lighting", ()),
        ("Smart Plugs", ()), ("Smart Switches", ()), ("Smart Sensors", ()), ("Home Automation", ()),
        ("Security Accessories", ()),
    )),
    ("Music & Instruments", (
        ("Guitars", ()), ("Keyboards", ()), ("Drums", ()), ("Microphones", ()), ("Speakers", ()),
        ("DJ Equipment", ()), ("Studio Equipment", ()), ("Instrument Accessories", ()),
    )),
    ("Arts, Crafts & Hobbies", (
        ("Art Supplies", ()), ("Drawing", ()), ("Painting", ()), ("Sewing", ()), ("Knitting", ()),
        ("Craft Materials", ()), ("DIY Crafts", ()), ("Collectibles", ()),
    )),
    ("Jewellery & Watches", (
        ("Jewellery", ()), ("Rings", ()), ("Necklaces", ()), ("Bracelets", ()), ("Earrings", ()),
        ("Watches", ()), ("Jewellery Accessories", ()),
    )),
    ("Travel & Luggage", (
        ("Suitcases", ()), ("Travel Bags", ()), ("Backpacks", ()), ("Travel Accessories", ()),
        ("Travel Organizers", ()), ("Camping & Travel Gear", ()),
    )),
    ("Groceries & Food", (
        ("Beverages", ()), ("Snacks", ()), ("Cooking Ingredients", ()), ("Baking Supplies", ()),
        ("Canned Foods", ()), ("Packaged Foods", ()), ("Fresh Foods", ()), ("Household Consumables", ()),
    )),
    ("Pet Supplies", (
        ("Dog Supplies", ()), ("Cat Supplies", ()), ("Bird Supplies", ()), ("Fish Supplies", ()),
        ("Pet Food", ()), ("Pet Grooming", ()), ("Pet Toys", ()), ("Pet Accessories", ()),
    )),
    ("Industrial & Business", (
        ("Industrial Equipment", ()), ("Construction Equipment", ()), ("Laboratory Equipment", ()),
        ("Commercial Equipment", ()), ("Packaging Equipment", ()), ("Restaurant Equipment", ()),
        ("Safety Equipment", ()), ("Business Supplies", ()),
    )),
    ("Gifts & Occasions", (
        ("Birthday Gifts", ()), ("Wedding Gifts", ()), ("Valentine's", ()), ("Graduation", ()),
        ("Christmas", ()), ("Party Supplies", ()), ("Decorations", ()), ("Corporate Gifts", ()),
    )),
    ("Handmade & Local Products", (
        ("African Crafts", ()), ("Handmade Decor", ()), ("Baskets", ()), ("Wood Products", ()),
        ("Local Art", ()), ("Handmade Accessories", ()), ("Traditional Products", ()),
    )),
    ("Other", (
        ("Miscellaneous", ()), ("Collectibles", ()), ("Other Products", ()),
    )),
)


BRAND_CATEGORIES = {
    'arduino': 'Arduino',
    'adafruit': 'Adafruit',
    'espressif': 'Espressif',
}

SAFE_CATEGORY_ALIASES = {
    'phone': 'smartphones',
    'phones': 'smartphones',
    'mobile phones': 'smartphones',
    'mobile phone': 'smartphones',
    'cell phones': 'smartphones',
    'laptop': 'laptops',
    'computer': 'desktop-computers',
    'computers': 'desktop-computers',
    'fashion': 'fashion-accessories',
    'clothes': 'clothing',
    'apparel': 'clothing',
    'shoe': 'shoes',
    'shoes': 'shoes',
    'home': 'home-living',
    'home accessories': 'home-accessories',
    'household': 'home-living',
    'sports': 'sports-outdoors',
    'sport': 'sports-outdoors',
    'beauty': 'beauty-personal-care',
    'personal care': 'beauty-personal-care',
    'toys': 'toys-games',
    'games': 'toys-games',
    'books': 'books-education',
    'book': 'books-education',
    'grocery': 'groceries-food',
    'groceries': 'groceries-food',
    'appliances': 'home-appliances',
    'electronics': 'electronics',
    'phone accessories': 'phone-accessories',
    'electronics accessories': 'electronic-accessories',
    'electronics components': 'electronic-components',
    'arduino': 'development-boards',
    'adafruit': 'development-boards',
    'espressif': 'development-boards',
}


def _normalized(value):
    value = unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def seed_marketplace_taxonomy(apps, schema_editor):
    Category = apps.get_model('products', 'Category')
    CategoryAttribute = apps.get_model('products', 'CategoryAttribute')
    Product = apps.get_model('products', 'Product')
    database = schema_editor.connection.alias
    categories = Category.objects.using(database)
    products = Product.objects.using(database)
    old_categories = list(categories.all().values('id', 'name', 'slug', 'parent_id'))
    category_by_slug = {}
    position = 0

    def upsert(name, parent=None, description=''):
        nonlocal position
        base_slug = slugify(name)
        slug = base_slug
        existing = categories.filter(slug=slug).first()
        if existing and existing.parent_id != (parent.pk if parent else None):
            if existing.parent_id is None and _normalized(existing.name) == _normalized(name):
                category = existing
            else:
                slug = f'{parent.slug}-{base_slug}' if parent else base_slug
                category = categories.filter(slug=slug).first()
        else:
            category = existing
        if category is None:
            category = categories.create(
                slug=slug,
                name=name,
                parent_id=parent.pk if parent else None,
            )
        category.name = name
        category.parent_id = parent.pk if parent else None
        category.is_active = True
        category.position = position
        category.description = description
        category.save(update_fields=('name', 'parent', 'is_active', 'position', 'description'))
        position += 1
        category_by_slug[slug] = category
        return category

    for department_name, children in TAXONOMY:
        department = upsert(department_name, description=f'Shop {department_name.lower()} products.')
        for child_name, subcategories in children:
            child = upsert(child_name, department)
            for subcategory_name, _ in subcategories:
                upsert(subcategory_name, child)

    miscellaneous = category_by_slug['miscellaneous']

    # Move products to safe canonical destinations without changing product records.
    for old in old_categories:
        normalized_name = _normalized(old['name'])
        brand = BRAND_CATEGORIES.get(slugify(old['name']))
        target_slug = SAFE_CATEGORY_ALIASES.get(normalized_name) or slugify(old['name'])
        target = category_by_slug.get(target_slug)
        if target is None:
            target = category_by_slug.get(SAFE_CATEGORY_ALIASES.get(normalized_name, '')) or miscellaneous

        old_queryset = products.using(database).filter(category_id=old['id'])
        if brand:
            old_queryset.filter(brand='').update(brand=brand)
        old_queryset.update(category_id=target.pk)

        if target.pk != old['id']:
            for attribute in CategoryAttribute.objects.using(database).filter(category_id=old['id']).iterator():
                if not CategoryAttribute.objects.using(database).filter(
                    category_id=target.pk, key=attribute.key,
                ).exists():
                    attribute.pk = None
                    attribute.category_id = target.pk
                    attribute.save(using=database)

        current = categories.using(database).filter(pk=old['id']).first()
        if current and current.slug not in category_by_slug:
            current.is_active = False
            current.save(update_fields=('is_active',))

    # Products without a category remain available in the safe fallback.
    products.using(database).filter(category__isnull=True).update(category_id=miscellaneous.pk)

    # Keep retired category records for auditability and to avoid breaking external references.
    categories.using(database).exclude(slug__in=category_by_slug).update(is_active=False)

    attributes = {
        'development-boards': (
            ('Voltage', 'voltage', 'text', True),
            ('Model', 'model', 'text', True),
        ),
        'laptops': (
            ('RAM', 'ram', 'text', True),
            ('Storage', 'storage', 'text', True),
            ('Screen Size', 'screen-size', 'measurement', True),
        ),
        'smartphones': (
            ('RAM', 'ram', 'text', True),
            ('Storage', 'storage', 'text', True),
            ('Screen Size', 'screen-size', 'measurement', True),
            ('Battery Capacity', 'battery-capacity', 'text', True),
        ),
        'mens-shoes': (
            ('Size', 'size', 'size', True),
            ('Material', 'material', 'text', True),
            ('Color', 'color', 'color', True),
        ),
        'womens-shoes': (
            ('Size', 'size', 'size', True),
            ('Material', 'material', 'text', True),
            ('Color', 'color', 'color', True),
        ),
        'clothing': (
            ('Size', 'size', 'size', True),
            ('Material', 'material', 'text', True),
            ('Color', 'color', 'color', True),
            ('Gender', 'gender', 'dropdown', True),
        ),
        'automotive': (
            ('Vehicle Compatibility', 'vehicle-compatibility', 'text', True),
            ('Model Year', 'model-year', 'text', True),
        ),
    }
    for category_slug, rows in attributes.items():
        category = category_by_slug.get(category_slug)
        if category is None:
            continue
        for index, (name, key, input_type, filterable) in enumerate(rows):
            CategoryAttribute.objects.using(database).get_or_create(
                category_id=category.pk,
                key=key,
                defaults={
                    'name': name,
                    'input_type': input_type,
                    'choices': ['Men', 'Women', 'Unisex'] if input_type == 'dropdown' else [],
                    'is_required': False,
                    'is_variant': input_type in ('size', 'color'),
                    'is_filterable': filterable,
                    'position': index,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0020_category_taxonomy_fields'),
    ]

    operations = [
        migrations.RunPython(seed_marketplace_taxonomy, migrations.RunPython.noop),
    ]
