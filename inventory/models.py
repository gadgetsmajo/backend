from django.db import models
from django.conf import settings
from products.models import Product


class StockMovement(models.Model):
    MOVEMENT_TYPES = [
        ('in',       'Stock In'),
        ('out',      'Stock Out'),
        ('adjust',   'Adjustment'),
        ('return',   'Return'),
    ]

    product   = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_movements')
    type      = models.CharField(max_length=10, choices=MOVEMENT_TYPES)
    quantity  = models.IntegerField()                          # positive = in, negative = out
    note      = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_movements'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_type_display()} {self.quantity} × {self.product.name}'
