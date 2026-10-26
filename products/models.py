from django.db import models
from django.utils.text import slugify
import uuid
import cloudinary.models
from django.conf import settings


class Category(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    image = cloudinary.models.CloudinaryField('image', folder='categories/', blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'categories'


class Product(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    short_description = models.CharField(max_length=300, blank=True, default='')
    long_description = models.TextField(blank=True, default='')
    image = cloudinary.models.CloudinaryField('image', folder='products/', blank=True, null=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rating = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
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

    def save(self, *args, **kwargs):
        self.name = self.name.strip().title()
        self.slug = f'{slugify(self.name)}-{self.uuid.hex[:12]}'
        super().save(*args, **kwargs)


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
