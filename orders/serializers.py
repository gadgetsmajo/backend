from rest_framework import serializers
from .models import Order, OrderItem, ServiceRating, Payment, ReturnRequest
from products.models import Product
from products.serializers import ProductSerializer


class PaymentSerializer(serializers.ModelSerializer):
    order_code = serializers.SerializerMethodField()

    def get_order_code(self, obj):
        return obj.order.code if obj.order else None

    class Meta:
        model = Payment
        fields = ('id', 'order_code', 'pesapal_order_tracking_id', 'merchant_reference', 'amount', 'currency', 'status', 'payment_method', 'description', 'created_at', 'updated_at')


class OrderItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source='product',
        write_only=True
    )
    # price is ignored on write — always taken from the product in the DB
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ('id', 'product', 'product_id', 'quantity', 'price')


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)
    has_service_rating = serializers.SerializerMethodField()
    user_name = serializers.CharField(source='user.name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    payment = serializers.SerializerMethodField()
    status_changed_by_name = serializers.SerializerMethodField()

    def get_has_service_rating(self, obj):
        return hasattr(obj, 'service_rating')

    def get_payment(self, obj):
        try:
            return {'status': obj.payment.status}
        except Exception:
            return None

    def get_status_changed_by_name(self, obj):
        return obj.status_changed_by.name if obj.status_changed_by else None

    class Meta:
        model = Order
        fields = ('id', 'code', 'status', 'subtotal', 'delivery_fee', 'total', 'items', 'delivery_address', 'phone', 'note', 'cancel_reason', 'has_service_rating', 'payment', 'user_name', 'user_email', 'status_changed_by_name', 'created_at', 'updated_at')
        read_only_fields = ('id', 'code', 'subtotal', 'delivery_fee', 'total', 'status', 'cancel_reason', 'status_changed_by_name', 'created_at', 'updated_at')

    def create(self, validated_data):
        from django.db import transaction
        from products.models import Product
        items_data = validated_data.pop('items')
        delivery_fee = validated_data.pop('delivery_fee', 5000)

        with transaction.atomic():
            # Lock product rows to prevent overselling
            product_ids = [item['product'].pk for item in items_data]
            locked = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=product_ids)}

            for item in items_data:
                product = locked[item['product'].pk]
                if product.stock < item['quantity']:
                    raise serializers.ValidationError(
                        f'Not enough stock for "{product.name}". Available: {product.stock}.'
                    )

            subtotal = sum(locked[item['product'].pk].price * item['quantity'] for item in items_data)
            total = subtotal + delivery_fee
            order = Order.objects.create(subtotal=subtotal, delivery_fee=delivery_fee, total=total, **validated_data)

            for item in items_data:
                product = locked[item['product'].pk]
                item['price'] = product.price
                OrderItem.objects.create(order=order, **item)
                # Stock is reserved but NOT deducted until payment is confirmed

        return order


class ServiceRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceRating
        fields = ('id', 'overall', 'areas', 'area_ratings', 'comment', 'created_at')
        read_only_fields = ('id', 'created_at')


class ReturnRequestSerializer(serializers.ModelSerializer):
    order_code = serializers.CharField(source='order.code', read_only=True)

    class Meta:
        model = ReturnRequest
        fields = ('id', 'order_code', 'reason', 'status', 'admin_note', 'refund_amount', 'refund_reference', 'created_at', 'updated_at')
        read_only_fields = ('id', 'status', 'admin_note', 'refund_amount', 'refund_reference', 'created_at', 'updated_at')


class AdminReturnRequestSerializer(ReturnRequestSerializer):
    customer_name = serializers.CharField(source='order.user.name', read_only=True)
    customer_email = serializers.EmailField(source='order.user.email', read_only=True)
    order_total = serializers.DecimalField(source='order.total', max_digits=10, decimal_places=2, read_only=True)
    payment_status = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()

    class Meta(ReturnRequestSerializer.Meta):
        fields = ReturnRequestSerializer.Meta.fields + (
            'customer_name', 'customer_email', 'order_total', 'payment_status', 'payment_method',
        )

    def get_payment_status(self, obj):
        try:
            return obj.order.payment.status
        except Payment.DoesNotExist:
            return None

    def get_payment_method(self, obj):
        try:
            return obj.order.payment.payment_method
        except Payment.DoesNotExist:
            return ''
