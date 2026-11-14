from rest_framework import serializers
from .models import Order, OrderItem, ServiceRating, Payment, ReturnRequest
from products.models import Product, ProductVariant
from products.serializers import ProductSerializer
from settings_app.models import District, PlatformSettings
from settings_app.pricing import platform_commission_amount, price_with_platform_charges
from users.models import CartItem


class PaymentSerializer(serializers.ModelSerializer):
    order_code = serializers.SerializerMethodField()

    def get_order_code(self, obj):
        return obj.order.code if obj.order else None

    class Meta:
        model = Payment
        fields = ('id', 'order_code', 'pesapal_order_tracking_id', 'merchant_reference', 'amount', 'currency', 'status', 'payment_method', 'description', 'created_at', 'updated_at')


class OrderItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    variant_id = serializers.IntegerField(read_only=True)
    trader_offer_id = serializers.IntegerField(read_only=True)
    variant_options = serializers.JSONField(read_only=True)
    variant_sku = serializers.CharField(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source='product',
        write_only=True
    )
    # price is ignored on write — always taken from the product in the DB
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ('id', 'product', 'product_id', 'trader_offer_id', 'variant_id', 'variant_options', 'variant_sku', 'quantity', 'price')


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    district_id = serializers.PrimaryKeyRelatedField(
        queryset=District.objects.all(),
        source='district',
        write_only=True,
    )
    village = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=150)
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
        fields = ('id', 'code', 'status', 'subtotal', 'delivery_fee', 'total', 'items', 'district_id', 'village', 'delivery_address', 'phone', 'note', 'cancel_reason', 'has_service_rating', 'payment', 'user_name', 'user_email', 'status_changed_by_name', 'created_at', 'updated_at')
        read_only_fields = ('id', 'code', 'subtotal', 'delivery_fee', 'total', 'status', 'cancel_reason', 'status_changed_by_name', 'created_at', 'updated_at')

    def create(self, validated_data):
        from django.db import transaction
        validated_data.pop('items', None)
        district = validated_data.pop('district')
        village = validated_data.pop('village', '').strip()
        user = validated_data.pop('user')
        validated_data.pop('delivery_address', None)

        with transaction.atomic():
            cart_items = list(
                CartItem.objects.select_for_update()
                .select_related('trader_offer')
                .filter(user=user)
                .order_by('product_id', 'trader_offer_id', 'variant_id')
            )
            if not cart_items:
                raise serializers.ValidationError({'detail': 'Your cart is empty.'})
            if len(cart_items) > 100:
                raise serializers.ValidationError({'detail': 'Your cart has too many different products.'})

            product_ids = [item.product_id for item in cart_items]
            locked = {
                product.pk: product
                for product in Product.objects.select_for_update().filter(pk__in=product_ids)
            }
            variant_ids = [item.variant_id for item in cart_items if item.variant_id]
            locked_variants = {
                variant.pk: variant
                for variant in ProductVariant.objects.select_for_update().filter(pk__in=variant_ids)
            }
            from traders.models import TraderProduct

            offer_ids = [item.trader_offer_id for item in cart_items if item.trader_offer_id]
            locked_offers = {
                offer.pk: offer
                for offer in TraderProduct.objects.select_for_update().select_related('trader').filter(
                    pk__in=offer_ids,
                    is_active=True,
                    review_status='approved',
                    trader__status='approved',
                    trader__is_visible=True,
                    trader__is_closed=False,
                )
            }

            for cart_item in cart_items:
                product = locked.get(cart_item.product_id)
                if not product or not product.is_active:
                    raise serializers.ValidationError({
                        'detail': 'A product in your cart is no longer available. Please refresh your cart.'
                    })
                offer = locked_offers.get(cart_item.trader_offer_id)
                if cart_item.trader_offer_id and (
                    not offer or offer.listing_product_id != product.pk
                ):
                    raise serializers.ValidationError(
                        {'detail': f'The selected seller offer for "{product.name}" is no longer available.'}
                    )
                variant = locked_variants.get(cart_item.variant_id)
                if cart_item.variant_options and not variant:
                    raise serializers.ValidationError(
                        {'detail': f'Select an available option for "{product.name}" before ordering.'}
                    )
                if not variant and product.requires_variant_selection:
                    raise serializers.ValidationError(
                        {'detail': f'Select all required options for "{product.name}" before ordering.'}
                    )
                if variant and (
                    (variant.trader_product_id != offer.pk if offer else variant.product_id != product.pk)
                    or not variant.is_active
                ):
                    raise serializers.ValidationError(
                        {'detail': f'The selected option for "{product.name}" is no longer available.'}
                    )
                offer_requires_variant = (
                    product.requires_variant_selection_for(offer.variants.filter(is_active=True))
                    if offer else False
                )
                if variant and (product.requires_variant_selection or offer_requires_variant) and not product.variant_has_required_options(variant):
                    raise serializers.ValidationError(
                        {'detail': f'The selected option for "{product.name}" is incomplete.'}
                    )
                if (
                    offer is None
                    and product.is_catalog_anchor
                    and (
                        (variant.stock if variant else product.stock) <= 0
                        or (variant.price if variant else product.price) <= 0
                    )
                ):
                    raise serializers.ValidationError(
                        {'detail': f'Choose an available seller offer for "{product.name}".'}
                    )
                available_stock = variant.stock if variant else offer.stock if offer else product.stock
                if cart_item.quantity < 1 or cart_item.quantity > 100 or available_stock < cart_item.quantity:
                    raise serializers.ValidationError(
                        {'detail': f'Not enough stock for "{product.name}". Available: {available_stock}.'}
                    )

            platform_settings = PlatformSettings.get()
            item_prices = {
                item.pk: price_with_platform_charges(
                    locked_variants[item.variant_id].price if item.variant_id
                    else locked_offers[item.trader_offer_id].price if item.trader_offer_id
                    else locked[item.product_id].price,
                    platform_settings,
                )
                for item in cart_items
            }
            subtotal = sum(
                item_prices[item.pk] * item.quantity
                for item in cart_items
            )
            delivery_fee = district.price
            total = subtotal + delivery_fee
            address_parts = [district.region, district.name, village]
            validated_data['delivery_address'] = ', '.join(part for part in address_parts if part)
            order = Order.objects.create(
                user=user,
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                total=total,
                **validated_data,
            )

            for cart_item in cart_items:
                product = locked[cart_item.product_id]
                offer = locked_offers.get(cart_item.trader_offer_id)
                variant = locked_variants.get(cart_item.variant_id)
                seller_price = variant.price if variant else offer.price if offer else product.price
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    trader_offer=offer,
                    variant=variant,
                    variant_options=variant.options if variant else cart_item.variant_options,
                    variant_sku=variant.sku if variant else '',
                    quantity=cart_item.quantity,
                    price=item_prices[cart_item.pk],
                    seller_price=seller_price,
                    platform_commission_pct=platform_settings.commission,
                    platform_commission=platform_commission_amount(
                        seller_price,
                        platform_settings,
                    ) * cart_item.quantity,
                )
            CartItem.objects.filter(pk__in=[item.pk for item in cart_items]).delete()

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
