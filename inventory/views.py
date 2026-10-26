from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Sum, Q
from products.models import Product
from .models import StockMovement
from .serializers import StockMovementSerializer


class InventorySummaryView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        products = Product.objects.all()
        total    = products.count()
        in_stock = products.filter(stock__gt=5).count()
        low      = products.filter(stock__gt=0, stock__lte=5).count()
        out      = products.filter(stock=0).count()

        low_stock_items = list(
            products.filter(stock__gt=0, stock__lte=5)
            .values('id', 'name', 'stock')
            .order_by('stock')
        )
        out_of_stock_items = list(
            products.filter(stock=0)
            .values('id', 'name', 'stock')
        )

        return Response({
            'total': total,
            'in_stock': in_stock,
            'low_stock': low,
            'out_of_stock': out,
            'low_stock_items': low_stock_items,
            'out_of_stock_items': out_of_stock_items,
        })


class StockMovementListCreateView(generics.ListCreateAPIView):
    serializer_class = StockMovementSerializer
    permission_classes = (permissions.IsAdminUser,)

    def get_queryset(self):
        qs = StockMovement.objects.select_related('product', 'created_by')
        product_id = self.request.query_params.get('product')
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs

    def perform_create(self, serializer):
        movement = serializer.save(created_by=self.request.user)
        # Update product stock
        product = movement.product
        product.stock = max(0, product.stock + movement.quantity)
        product.save(update_fields=['stock'])
