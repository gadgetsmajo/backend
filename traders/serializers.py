from rest_framework import serializers
from .models import TraderApplication, TraderProduct, TraderSale, TraderExpense, TraderOrderItem, TraderInventoryItem, TraderStockMovement


class TraderApplicationSerializer(serializers.ModelSerializer):
    reviewed_by_name = serializers.CharField(source='reviewed_by.name', read_only=True, default=None)

    class Meta:
        model = TraderApplication
        fields = '__all__'
        read_only_fields = ('id', 'uuid', 'status', 'admin_note', 'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'user', 'created_at', 'updated_at')

    def validate_email(self, value):
        # Allow re-application if existing record is rejected
        qs = TraderApplication.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.filter(status__in=('pending', 'approved')).exists():
            raise serializers.ValidationError('An active application with this email already exists.')
        # Delete old rejected record so new one can be created cleanly
        qs.filter(status='rejected').delete()
        return value


class TraderApplicationAdminSerializer(serializers.ModelSerializer):
    reviewed_by_name = serializers.CharField(source='reviewed_by.name', read_only=True, default=None)
    user_email = serializers.CharField(source='user.email', read_only=True, default=None)
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = TraderApplication
        fields = '__all__'

    def get_logo_url(self, obj):
        if obj.logo:
            return obj.logo.url
        return None


class TraderProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    category_id = serializers.IntegerField(source='category.id', read_only=True, allow_null=True, default=None)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = TraderProduct
        fields = (
            'id', 'uuid', 'name', 'short_description', 'long_description', 'description',
            'price', 'original_price', 'delivery_fee', 'stock',
            'category_id', 'category_name',
            'image_url', 'is_active', 'is_featured', 'is_new_deal',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'uuid', 'image_url', 'category_id', 'category_name', 'created_at', 'updated_at')

    def get_image_url(self, obj):
        if obj.image:
            return obj.image.url
        return obj.image_url or None


class TraderSaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraderSale
        fields = ('id', 'uuid', 'product', 'product_name', 'quantity', 'unit_price', 'total', 'customer_name', 'note', 'created_at')
        read_only_fields = ('id', 'uuid', 'created_at')


class TraderExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraderExpense
        fields = ('id', 'uuid', 'description', 'amount', 'date', 'note', 'created_at')
        read_only_fields = ('id', 'uuid', 'created_at')


class TraderInventoryItemSerializer(serializers.ModelSerializer):
    product_name  = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()
    product_price = serializers.DecimalField(source='product.price', max_digits=12, decimal_places=2, read_only=True)
    product_stock = serializers.IntegerField(source='product.stock', read_only=True)
    product_uuid  = serializers.CharField(source='product.uuid', read_only=True)

    class Meta:
        model = TraderInventoryItem
        fields = ('id', 'product', 'product_uuid', 'product_name', 'product_image', 'product_price',
                  'product_stock', 'quantity', 'cost_price', 'location', 'note', 'updated_at', 'created_at')
        read_only_fields = ('id', 'product_uuid', 'product_name', 'product_image', 'product_price',
                            'product_stock', 'updated_at', 'created_at')

    def get_product_image(self, obj):
        try:
            return obj.product.image.url
        except Exception:
            return obj.product.image_url or None


class TraderStockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='item.product.name', read_only=True)

    class Meta:
        model = TraderStockMovement
        fields = ('id', 'item', 'product_name', 'type', 'quantity', 'note', 'created_at')
        read_only_fields = ('id', 'product_name', 'created_at')


class TraderOrderItemSerializer(serializers.ModelSerializer):
    order_code        = serializers.CharField(source='order_item.order.code', read_only=True)
    order_id          = serializers.IntegerField(source='order_item.order.id', read_only=True)
    order_status      = serializers.CharField(source='order_item.order.status', read_only=True)
    order_created_at  = serializers.DateTimeField(source='order_item.order.created_at', read_only=True)
    delivery_address  = serializers.CharField(source='order_item.order.delivery_address', read_only=True)
    product_name      = serializers.CharField(source='order_item.product.name', read_only=True)
    product_image     = serializers.SerializerMethodField()
    quantity          = serializers.IntegerField(source='order_item.quantity', read_only=True)
    price             = serializers.DecimalField(source='order_item.price', max_digits=10, decimal_places=2, read_only=True)
    order_item_id     = serializers.IntegerField(source='order_item.id', read_only=True)
    status_changed_by_name = serializers.CharField(source='status_changed_by.name', read_only=True, default=None)
    ready_at          = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TraderOrderItem
        fields = (
            'id', 'order_item_id', 'order_code', 'order_id', 'order_status',
            'order_created_at', 'delivery_address',
            'product_name', 'product_image', 'quantity', 'price',
            'status', 'note', 'status_changed_by_name', 'ready_at', 'updated_at',
        )
        read_only_fields = ('id', 'order_item_id', 'order_code', 'order_id', 'order_status',
                            'order_created_at', 'delivery_address',
                            'product_name', 'product_image', 'quantity', 'price',
                            'status_changed_by_name', 'updated_at')

    def get_product_image(self, obj):
        try:
            return obj.order_item.product.image.url
        except Exception:
            return None
