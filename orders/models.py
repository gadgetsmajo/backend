from django.db import models
from django.conf import settings
from django.utils.crypto import get_random_string
from products.models import Product


class Payment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('invalid', 'Invalid'),
        ('cancelled', 'Cancelled'),
    ]
    order = models.OneToOneField('Order', on_delete=models.CASCADE, related_name='payment', null=True, blank=True)
    pesapal_order_tracking_id = models.CharField(max_length=100, unique=True)
    confirmation_code = models.CharField(max_length=100, blank=True)
    merchant_reference = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='UGX')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Payment {self.pesapal_order_tracking_id} — {self.status}'



def generate_order_code():
    import random
    while True:
        numeric = ''.join([str(random.randint(0, 9)) for _ in range(8)])
        suffix = get_random_string(5, 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
        code = f'{numeric}-{suffix}'
        if not Order.objects.filter(code=code).exists():
            return code


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Confirmed'),
        ('shipped', 'Shipped'),
        ('ready_for_pickup', 'Ready for Pickup'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    code = models.CharField(max_length=14, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=5000)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='order_status_changes'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_order_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Order {self.code} - {self.user.email}'


class ServiceRating(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='service_rating')
    overall = models.PositiveSmallIntegerField()          # 1–5
    areas = models.JSONField(default=list)                # ['delivery_speed', ...]
    area_ratings = models.JSONField(default=dict)         # {'delivery_speed': 4, ...}
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'ServiceRating for {self.order.code} — {self.overall}★'


class ReturnRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Refund Processing'),
        ('approved', 'Approved'),
        ('refunded', 'Refunded'),
        ('rejected', 'Rejected'),
        ('refund_failed', 'Refund Failed'),
    ]
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='return_request')
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    refund_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Return for {self.order.code} — {self.status}'


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f'{self.quantity}x {self.product.name}'
