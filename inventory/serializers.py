from rest_framework import serializers
from .models import StockMovement


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.name', read_only=True, default=None)

    class Meta:
        model = StockMovement
        fields = ['id', 'product', 'product_name', 'type', 'quantity', 'note', 'created_by_name', 'created_at']
        read_only_fields = ['id', 'product_name', 'created_by_name', 'created_at']
