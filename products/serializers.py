from rest_framework import serializers
from django.utils.text import slugify
from django.db.models import Avg, Count
from .models import Category, Product, ProductImage, FlashSale, ProductReview, ReviewImage
from settings_app.models import PlatformSettings


def _apply_commission(price):
    """Return price * (1 + commission/100) * (1 + vat/100), rounded to 2dp."""
    try:
        settings = PlatformSettings.get()
        commission = float(settings.commission)
        vat = float(settings.vat)
        multiplier = (1 + commission / 100) * (1 + vat / 100)
        if multiplier != 1:
            return round(float(price) * multiplier, 2)
    except Exception:
        pass
    return float(price)


class CategorySerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Category
        fields = ('id', 'uuid', 'name', 'slug', 'image')
        extra_kwargs = {'slug': {'required': False}}

    def validate(self, attrs):
        slug = attrs.get('slug') or slugify(attrs.get('name', ''))
        if not self.instance:
            original = slug
            counter = 1
            while Category.objects.filter(slug=slug).exists():
                slug = f'{original}-{counter}'
                counter += 1
        attrs['slug'] = slug
        return attrs

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        if instance.image:
            try:
                rep['image'] = instance.image.url
            except Exception:
                rep['image'] = None
        return rep


class ProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ('id', 'url', 'order')

    def get_url(self, obj):
        try:
            return obj.image.url
        except Exception:
            return None


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True
    )
    image_url = serializers.SerializerMethodField(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    is_featured = serializers.BooleanField(required=False)
    is_new_deal = serializers.BooleanField(required=False)
    reviews_count = serializers.SerializerMethodField()
    seller_uuid = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ('id', 'uuid', 'name', 'slug', 'category', 'category_id',
                  'price', 'original_price', 'image_url', 'images',
                  'short_description', 'long_description', 'delivery_fee',
                  'rating', 'stock', 'is_active', 'is_featured', 'is_new_deal', 'seller_uuid',
                  'created_at', 'reviews_count')
        read_only_fields = ('id', 'uuid', 'slug', 'rating', 'created_at')

    def get_reviews_count(self, obj):
        return obj.reviews.filter(status='published').count()

    def get_seller_uuid(self, obj):
        trader = obj.trader or (obj.trader_product.trader if obj.trader_product_id else None)
        if not trader or trader.status != 'approved' or not trader.is_visible or trader.is_closed:
            return None
        return str(trader.uuid)

    def get_image_url(self, obj):
        if obj.image:
            try:
                return obj.image.url
            except Exception:
                pass
        return None

    def create(self, validated_data):
        validated_data['is_active'] = True
        return super().create(validated_data)

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['image'] = rep.get('image_url')
        rep['price'] = str(_apply_commission(instance.price))
        if instance.original_price:
            rep['original_price'] = str(_apply_commission(instance.original_price))
        return rep


class ReviewImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ReviewImage
        fields = ('id', 'url', 'uploaded_at')

    def get_url(self, obj):
        try:
            url = obj.image.url
            return url if url else None
        except Exception:
            return None


class ProductReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True)
    user_avatar = serializers.SerializerMethodField()
    images = ReviewImageSerializer(many=True, read_only=True)
    order = serializers.PrimaryKeyRelatedField(read_only=True)
    order_item = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ProductReview
        fields = (
            'id', 'user_name', 'user_avatar',
            'overall_rating', 'performance_rating', 'battery_life_rating',
            'product_quality_rating', 'condition_rating', 'value_for_money_rating',
            'design_rating', 'features_rating', 'size_fit_rating',
            'review_text', 'verified_purchase', 'status',
            'images',
            'order', 'order_item',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'user_name', 'user_avatar', 'verified_purchase',
                            'status', 'images', 'created_at', 'updated_at')
        extra_kwargs = {
            'overall_rating': {'min_value': 1, 'max_value': 5},
            'performance_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'battery_life_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'product_quality_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'condition_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'value_for_money_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'design_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'features_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'size_fit_rating': {'min_value': 1, 'max_value': 5, 'required': False, 'allow_null': True},
            'review_text': {'required': False, 'allow_blank': True, 'max_length': 500},
        }

    def get_user_avatar(self, obj):
        try:
            url = obj.user.avatar.url
            return url if url else None
        except Exception:
            return None

    def create(self, validated_data):
        return ProductReview.objects.create(**validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('order', None)
        validated_data.pop('order_item', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        return instance


class RatingSummarySerializer(serializers.Serializer):
    average = serializers.FloatField()
    total = serializers.IntegerField()
    breakdown = serializers.DictField(child=serializers.IntegerField())
    with_photos = serializers.IntegerField()


class FlashSaleSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), source='product', write_only=True
    )
    stock_left = serializers.IntegerField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    discount_pct = serializers.SerializerMethodField()

    class Meta:
        model = FlashSale
        fields = ('id', 'product', 'product_id', 'flash_price', 'ends_at',
                  'stock_limit', 'stock_sold', 'stock_left', 'is_active',
                  'is_expired', 'discount_pct', 'created_at')
        read_only_fields = ('id', 'stock_sold', 'created_at')

    def get_discount_pct(self, obj):
        orig = obj.product.original_price or obj.product.price
        commissioned_flash = _apply_commission(obj.flash_price)
        commissioned_orig = _apply_commission(orig)
        if commissioned_orig and commissioned_orig > commissioned_flash:
            return round((1 - commissioned_flash / commissioned_orig) * 100)
        return 0

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['flash_price'] = str(_apply_commission(instance.flash_price))
        return rep

    def validate(self, attrs):
        from django.utils import timezone
        product = attrs.get('product') or (self.instance.product if self.instance else None)
        flash_price = attrs.get('flash_price')
        stock_limit = attrs.get('stock_limit')
        ends_at = attrs.get('ends_at')

        if product is None:
            raise serializers.ValidationError({'product_id': 'Product is required.'})

        # flash_price must be less than the product's current price
        if flash_price is not None and flash_price >= product.price:
            raise serializers.ValidationError({
                'flash_price': f'Flash price must be less than the product price (UGX {product.price:,.0f}).'
            })

        # stock_limit must not exceed available product stock
        if stock_limit is not None and stock_limit > product.stock:
            raise serializers.ValidationError({
                'stock_limit': f'Stock limit ({stock_limit}) cannot exceed available product stock ({product.stock}).'
            })

        # ends_at must be in the future
        if ends_at is not None and ends_at <= timezone.now():
            raise serializers.ValidationError({
                'ends_at': 'End time must be in the future.'
            })

        # prevent duplicate active flash sale for the same product
        if product:
            qs = FlashSale.objects.filter(
                product=product,
                is_active=True,
                ends_at__gt=timezone.now(),
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    'product_id': f'"{product.name}" already has an active flash sale.'
                })

        return attrs
