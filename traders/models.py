import cloudinary.models
from django.db import models
from django.conf import settings
import uuid


class TraderApplication(models.Model):
    STATUS = [
        ('pending',  'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    BUSINESS_TYPES = [
        ('sole_proprietor', 'Sole Proprietor'),
        ('partnership',     'Partnership'),
        ('limited_company', 'Limited Company'),
        ('other',           'Other'),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # Personal info
    full_name       = models.CharField(max_length=150)
    email           = models.EmailField(unique=True)
    phone           = models.CharField(max_length=30)
    national_id     = models.CharField(max_length=50, blank=True)

    # Business info
    business_name   = models.CharField(max_length=255)
    business_type   = models.CharField(max_length=20, choices=BUSINESS_TYPES)
    business_reg_no = models.CharField(max_length=100, blank=True)
    tin             = models.CharField(max_length=50, blank=True, verbose_name='TIN')
    location        = models.CharField(max_length=255)
    district        = models.CharField(max_length=100, blank=True)
    website         = models.URLField(blank=True)

    # What they want to sell
    product_categories = models.TextField(help_text='Categories/products they intend to sell')
    monthly_volume     = models.CharField(max_length=100, blank=True, help_text='Expected monthly sales volume')
    experience         = models.TextField(blank=True, help_text='Trading/business experience')

    # Business profile extras
    logo         = cloudinary.models.CloudinaryField('image', folder='trader_logos/', blank=True, null=True)
    bio          = models.TextField(blank=True, help_text='Short business description shown on store')
    is_visible   = models.BooleanField(default=True, help_text='If False, all trader products are hidden from store')
    is_closed    = models.BooleanField(default=False, help_text='Trader has closed their shop (soft close)')

    # Agreement
    agreed_to_terms = models.BooleanField(default=False)

    # Status
    status       = models.CharField(max_length=10, choices=STATUS, default='pending')
    admin_note   = models.TextField(blank=True)
    reviewed_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_trader_applications'
    )
    reviewed_at  = models.DateTimeField(null=True, blank=True)

    # Linked user account (set on approval)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='trader_application'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.business_name} — {self.status}'


class TraderFollower(models.Model):
    trader = models.ForeignKey(TraderApplication, on_delete=models.CASCADE, related_name='follower_records')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='followed_traders')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('trader', 'user'), name='unique_trader_follower'),
        ]


class TraderProduct(models.Model):
    uuid        = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    trader      = models.ForeignKey(TraderApplication, on_delete=models.CASCADE, related_name='products')
    name        = models.CharField(max_length=255)
    short_description = models.CharField(max_length=300, blank=True, default='')
    long_description  = models.TextField(blank=True, default='')
    description = models.TextField(blank=True)  # legacy
    price       = models.DecimalField(max_digits=12, decimal_places=2)
    original_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    delivery_fee   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock       = models.PositiveIntegerField(default=0)
    category    = models.ForeignKey('products.Category', on_delete=models.SET_NULL, null=True, blank=True)
    image_url   = models.URLField(blank=True)  # legacy
    image       = cloudinary.models.CloudinaryField('image', folder='trader_products/', blank=True, null=True)
    is_active   = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_new_deal = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.trader.business_name} — {self.name}'


class TraderSale(models.Model):
    uuid        = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    trader      = models.ForeignKey(TraderApplication, on_delete=models.CASCADE, related_name='sales')
    product     = models.ForeignKey(TraderProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    product_name = models.CharField(max_length=255)
    quantity    = models.PositiveIntegerField(default=1)
    unit_price  = models.DecimalField(max_digits=12, decimal_places=2)
    total       = models.DecimalField(max_digits=12, decimal_places=2)
    customer_name = models.CharField(max_length=150, blank=True)
    note        = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.trader.business_name} — {self.product_name} x{self.quantity}'


class TraderExpense(models.Model):
    uuid        = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    trader      = models.ForeignKey(TraderApplication, on_delete=models.CASCADE, related_name='expenses')
    description = models.CharField(max_length=255)
    amount      = models.DecimalField(max_digits=12, decimal_places=2)
    date        = models.DateField()
    note        = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.trader.business_name} — {self.description}'


class TraderInventoryItem(models.Model):
    """A product tracked in the trader's inventory."""
    trader      = models.ForeignKey(TraderApplication, on_delete=models.CASCADE, related_name='inventory_items')
    product     = models.ForeignKey(TraderProduct, on_delete=models.CASCADE, related_name='inventory_items')
    quantity    = models.IntegerField(default=0)
    cost_price  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    location    = models.CharField(max_length=255, blank=True)
    note        = models.TextField(blank=True)
    updated_at  = models.DateTimeField(auto_now=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('trader', 'product')
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.trader.business_name} — {self.product.name} ({self.quantity})'


class TraderStockMovement(models.Model):
    TYPES = [
        ('in',     'Stock In'),
        ('out',    'Stock Out'),
        ('adjust', 'Adjustment'),
        ('return', 'Return'),
    ]
    trader      = models.ForeignKey(TraderApplication, on_delete=models.CASCADE, related_name='stock_movements')
    item        = models.ForeignKey(TraderInventoryItem, on_delete=models.CASCADE, related_name='movements')
    type        = models.CharField(max_length=10, choices=TYPES)
    quantity    = models.IntegerField()   # positive = in, negative = out
    note        = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_type_display()} {self.quantity} × {self.item.product.name}'


class TraderOrderItem(models.Model):
    """Tracks a trader's preparation status for each order item that belongs to their products."""
    STATUS_CHOICES = [
        ('pending',   'Pending'),
        ('preparing', 'Preparing'),
        ('ready',     'Ready'),
    ]
    trader            = models.ForeignKey(TraderApplication, on_delete=models.CASCADE, related_name='order_items')
    order_item        = models.ForeignKey('orders.OrderItem', on_delete=models.CASCADE, related_name='trader_status')
    status            = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    note              = models.TextField(blank=True)
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='trader_order_status_changes'
    )
    ready_at          = models.DateTimeField(null=True, blank=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('trader', 'order_item')
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.trader.business_name} — item {self.order_item_id} [{self.status}]'
