from django.db import models
from django.db.models import Q
from django.utils.text import slugify
import uuid
import cloudinary.models
from django.conf import settings


class Category(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, default='')
    image = cloudinary.models.CloudinaryField('image', folder='categories/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children',
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ('position', 'name')


class CategoryAttribute(models.Model):
    INPUT_TYPES = (
        ('text', 'Text'),
        ('number', 'Number'),
        ('dropdown', 'Dropdown'),
        ('multi_select', 'Multi-select'),
        ('boolean', 'Boolean'),
        ('measurement', 'Measurement'),
        ('color', 'Color'),
        ('size', 'Size'),
    )

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='attributes')
    name = models.CharField(max_length=100)
    key = models.SlugField(max_length=100)
    input_type = models.CharField(max_length=20, choices=INPUT_TYPES, default='text')
    choices = models.JSONField(default=list, blank=True)
    is_required = models.BooleanField(default=False)
    is_variant = models.BooleanField(default=False)
    is_filterable = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ('position', 'name')
        constraints = [
            models.UniqueConstraint(fields=('category', 'key'), name='unique_category_attribute_key'),
        ]

    def __str__(self):
        return f'{self.category.name}: {self.name}'


class Product(models.Model):
    CONDITION_CHOICES = (
        ('new', 'New'),
        ('used', 'Used'),
        ('refurbished', 'Refurbished'),
    )
    REVIEW_STATUSES = (
        ('draft', 'Draft'),
        ('pending_review', 'Pending review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('changes_required', 'Changes required'),
        ('disabled', 'Disabled'),
        ('archived', 'Archived'),
    )

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    brand = models.CharField(max_length=120, blank=True, default='')
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='new')
    tags = models.JSONField(default=list, blank=True)
    specifications = models.JSONField(default=dict, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    short_description = models.CharField(max_length=300, blank=True, default='')
    long_description = models.TextField(blank=True, default='')
    image = cloudinary.models.CloudinaryField('image', folder='products/', blank=True, null=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rating = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    review_status = models.CharField(max_length=20, choices=REVIEW_STATUSES, default='approved')
    review_note = models.TextField(blank=True, default='')
    trader = models.ForeignKey(
        'traders.TraderApplication', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='store_products'
    )
    trader_product = models.OneToOneField(
        'traders.TraderProduct', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='public_product'
    )
    is_featured = models.BooleanField(default=False)
    is_new_deal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def required_variant_keys(self):
        if not self.category_id:
            return set()
        return set(
            self.category.attributes.filter(is_variant=True, is_required=True)
            .values_list('key', flat=True)
        )

    @property
    def requires_variant_selection(self):
        required_keys = self.required_variant_keys
        if not required_keys:
            return False
        variants = list(self.variants.all())
        return any(
            isinstance(variant.options, dict) and required_keys.issubset(variant.options)
            for variant in variants
        )

    def variant_has_required_options(self, variant):
        required_keys = self.required_variant_keys
        return bool(required_keys) and isinstance(variant.options, dict) and required_keys.issubset(variant.options)

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        update_fields = kwargs.get('update_fields')
        if (
            (update_fields is None or 'short_description' in update_fields)
            and isinstance(self.short_description, str)
        ):
            self.short_description = self.short_description[:300]
        self.slug = f'{slugify(self.name)}-{uuid.UUID(str(self.uuid)).hex[:12]}'
        super().save(*args, **kwargs)


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=100, blank=True, default='')
    options = models.JSONField(default=dict)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    compare_at_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    weight = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    image = cloudinary.models.CloudinaryField('image', folder='product_variants/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('id',)
        constraints = [
            models.UniqueConstraint(
                fields=('sku',),
                condition=~Q(sku=''),
                name='unique_nonempty_product_variant_sku',
            ),
        ]

    def __str__(self):
        values = ' / '.join(str(value) for value in self.options.values())
        return f'{self.product.name} — {values or self.sku or self.pk}'


class FlashSale(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='flash_sales')
    flash_price = models.DecimalField(max_digits=10, decimal_places=2)
    ends_at = models.DateTimeField()
    stock_limit = models.PositiveIntegerField(default=0)
    stock_sold = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Flash: {self.product.name} @ {self.flash_price}'

    @property
    def stock_left(self):
        return max(0, self.stock_limit - self.stock_sold)

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.ends_at


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = cloudinary.models.CloudinaryField('image', folder='products/')
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f'Image for {self.product.name}'


class ProductReview(models.Model):
    STATUS_CHOICES = [('published', 'Published'), ('hidden', 'Hidden')]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, related_name='product_reviews')
    order_item = models.ForeignKey('orders.OrderItem', on_delete=models.SET_NULL, null=True, related_name='review')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='product_reviews')

    overall_rating = models.PositiveSmallIntegerField()          # 1–5 required
    performance_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    battery_life_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    product_quality_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    condition_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    value_for_money_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    design_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    features_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    size_fit_rating = models.PositiveSmallIntegerField(null=True, blank=True)

    review_text = models.TextField(blank=True, default='')
    verified_purchase = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='published')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('product', 'user', 'order'), name='unique_product_user_order_review'),
        ]

    def __str__(self):
        return f'{self.user.email} → {self.product.name} ({self.overall_rating}★)'


class ReviewImage(models.Model):
    review = models.ForeignKey(ProductReview, on_delete=models.CASCADE, related_name='images')
    image = cloudinary.models.CloudinaryField('image', folder='review_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Image for review {self.review_id}'
