import bleach
from html import escape
from uuid import UUID

from django.core.cache import cache
from django.db.models import Avg, Count, F, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, filters, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .pagination import ProductPagination
from .models import Category, Product, ProductImage, FlashSale, ProductReview, ReviewImage
from .serializers import (
    CategorySerializer, ProductSerializer, ProductImageSerializer,
    FlashSaleSerializer,
    ProductReviewSerializer, RatingSummarySerializer,
)
from .permissions import IsAdminOrReadOnly
from orders.models import OrderItem
from users.models import UserBehaviour


CATEGORY_CACHE_TTL = 60 * 30  # 30 minutes
FLASH_SALE_CACHE_TTL = 60 * 5  # 5 minutes


class IsTraderProductOwner(permissions.BasePermission):
    """Only a trader owning the product may mutate its flash-sale record; staff cannot touch trader-owned products."""

    def _get_product(self, request, view):
        if hasattr(view, 'get_object'):
            try:
                obj = view.get_object()
            except Exception:
                obj = None
            if obj is not None and hasattr(obj, 'product'):
                return obj.product
        product_id = request.data.get('product_id') or request.data.get('product')
        if not product_id:
            return None
        try:
            return Product.objects.select_related('trader', 'trader_product__trader').get(pk=product_id)
        except Product.DoesNotExist:
            return None

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not request.user or not request.user.is_authenticated:
            return False

        product = self._get_product(request, view)
        if product is None:
            return False

        trader_app = getattr(request.user, 'trader_application', None)
        if request.user.is_staff:
            return product.trader_id is None and (product.trader_product_id is None or product.trader_product.trader_id is None)

        if trader_app is None:
            return False

        if product.trader_id == trader_app.id:
            return True
        return bool(product.trader_product and product.trader_product.trader_id == trader_app.id)


class CategoryListView(generics.ListCreateAPIView):
    queryset = Category.objects.all().order_by('name')
    serializer_class = CategorySerializer
    permission_classes = (IsAdminOrReadOnly,)

    def list(self, request, *args, **kwargs):
        cached = cache.get('categories:list')
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set('categories:list', response.data, CATEGORY_CACHE_TTL)
        return response

    def perform_create(self, serializer):
        serializer.save()
        cache.delete('categories:list')


class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = (IsAdminOrReadOnly,)

    def perform_update(self, serializer):
        serializer.save()
        cache.delete('categories:list')

    def perform_destroy(self, instance):
        instance.delete()
        cache.delete('categories:list')


PRODUCT_CACHE_TTL = 60 * 15  # 15 minutes


class ProductListView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = (IsAdminOrReadOnly,)
    pagination_class = ProductPagination
    filter_backends = (filters.SearchFilter, filters.OrderingFilter)
    search_fields = ('name', 'category__name')
    ordering_fields = ('price', 'rating', 'created_at')

    def get_queryset(self):
        qs = Product.objects.all().select_related('category', 'trader', 'trader_product__trader').prefetch_related('images')
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category__slug=category)
        seller_uuid = self.request.query_params.get('seller')
        if seller_uuid:
            try:
                seller_uuid = UUID(seller_uuid)
            except ValueError:
                return qs.none()
            visible_seller = Q(trader__uuid=seller_uuid, trader__status='approved', trader__is_visible=True, trader__is_closed=False)
            visible_seller |= Q(trader_product__trader__uuid=seller_uuid, trader_product__trader__status='approved', trader_product__trader__is_visible=True, trader_product__trader__is_closed=False)
            qs = qs.filter(visible_seller)
        if self.request.query_params.get('top_bought') == 'true':
            qs = qs.annotate(
                bought_quantity=Coalesce(
                    Sum('orderitem__quantity', filter=Q(orderitem__order__status='delivered')),
                    Value(0),
                    output_field=IntegerField(),
                )
            ).filter(bought_quantity__gt=0).order_by('-bought_quantity', '-created_at')
        else:
            qs = qs.order_by('-created_at')
        return qs

    def list(self, request, *args, **kwargs):
        if request.method != 'GET' or request.query_params:
            return super().list(request, *args, **kwargs)
        cached = cache.get('products:list')
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set('products:list', response.data, PRODUCT_CACHE_TTL)
        return response

    def perform_create(self, serializer):
        cover = self.request.FILES.get('image')
        product = serializer.save(**(({'image': cover}) if cover else {}))
        for i, img in enumerate(self.request.FILES.getlist('images')):
            ProductImage.objects.create(product=product, image=img, order=i)
        cache.delete('products:list')


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.all().select_related('category', 'trader', 'trader_product__trader').prefetch_related('images')
    serializer_class = ProductSerializer
    permission_classes = (IsAdminOrReadOnly,)

    def retrieve(self, request, *args, **kwargs):
        pk = kwargs.get('pk')
        cache_key = f'products:detail:{pk}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().retrieve(request, *args, **kwargs)
        cache.set(cache_key, response.data, PRODUCT_CACHE_TTL)
        return response

    def perform_update(self, serializer):
        cover = self.request.FILES.get('image')
        product = serializer.save(**(({'image': cover}) if cover else {}))
        files = self.request.FILES.getlist('images')
        if files:
            start = product.images.count()
            for i, img in enumerate(files):
                ProductImage.objects.create(product=product, image=img, order=start + i)
        cache.delete(f'products:detail:{product.pk}')
        cache.delete('products:list')

    def perform_destroy(self, instance):
        cache.delete(f'products:detail:{instance.pk}')
        cache.delete('products:list')
        instance.delete()


class ProductStockAddView(APIView):
    """POST /api/products/<pk>/stock/ — admin or the product's trader can add stock."""
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        if not request.user.is_staff:
            trader_app = getattr(request.user, 'trader_application', None)
            if not trader_app or product.trader_id != trader_app.id:
                return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qty = int(request.data.get('quantity', 0))
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid quantity.'}, status=status.HTTP_400_BAD_REQUEST)
        if qty <= 0:
            return Response({'detail': 'Quantity must be positive.'}, status=status.HTTP_400_BAD_REQUEST)
        Product.objects.filter(pk=pk).update(stock=F('stock') + qty)
        product.refresh_from_db(fields=['stock'])
        return Response({'id': product.pk, 'stock': product.stock})


class ProductImageDeleteView(APIView):
    """DELETE /api/products/<pk>/images/<img_pk>/"""
    permission_classes = (permissions.IsAdminUser,)

    def delete(self, request, pk, img_pk):
        img = get_object_or_404(ProductImage, pk=img_pk, product_id=pk)
        img.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductSlugDetailView(generics.RetrieveAPIView):
    queryset = Product.objects.all().select_related('category', 'trader', 'trader_product__trader')
    serializer_class = ProductSerializer
    permission_classes = (IsAdminOrReadOnly,)
    lookup_field = 'slug'
    lookup_url_kwarg = 'slug'

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if request.user.is_authenticated and instance.category:
            UserBehaviour.get_for_user(request.user).track_category(instance.category.slug, score=1, product_id=instance.pk)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class RecommendedProductsView(APIView):
    """GET /api/products/recommended/ — personalized list for the landing page."""
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        products = _get_recommended_products_for_user(request.user if getattr(request, 'user', None) and request.user.is_authenticated else None, limit=12)
        serializer = ProductSerializer(products, many=True)
        return Response(serializer.data)


def _get_recommended_products_for_user(user, limit=12):
    qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('images').order_by('-rating', '-created_at')

    if not user or not user.is_authenticated:
        return list(qs[:limit])

    behaviour = UserBehaviour.objects.filter(user=user).first()
    category_scores = dict((behaviour.category_scores or {})) if behaviour else {}

    user_order_categories = set(
        OrderItem.objects.filter(order__user=user)
        .exclude(product__category__isnull=True)
        .values_list('product__category__slug', flat=True)
    )

    for category_slug in user_order_categories:
        category_scores[category_slug] = category_scores.get(category_slug, 0) + 25

    seen_product_ids = set(OrderItem.objects.filter(order__user=user).values_list('product_id', flat=True))
    if behaviour:
        seen_product_ids.update(int(pid) for pid in (behaviour.recent_product_ids or []))

    if not category_scores:
        return list(qs.exclude(pk__in=seen_product_ids)[:limit])

    ranked = []
    for product in qs.exclude(pk__in=seen_product_ids):
        slug = product.category.slug if product.category else ''
        score = float(category_scores.get(slug, 0)) * 20.0
        score += float(product.rating or 0) * 4.0
        if product.is_featured:
            score += 30
        if product.is_new_deal:
            score += 15
        if product.original_price and product.price < product.original_price:
            score += 10
        ranked.append((score, product))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [product for _, product in ranked[:limit]]


# ── Flash Sales ─────────────────────────────────────────────────────────────

class FlashSaleListCreateView(generics.ListCreateAPIView):
    serializer_class = FlashSaleSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsTraderProductOwner()]

    def get_queryset(self):
        from django.utils import timezone
        qs = FlashSale.objects.select_related('product__category').prefetch_related('product__images')
        if self.request.user.is_authenticated and not self.request.user.is_staff:
            trader = getattr(self.request.user, 'trader_application', None)
            if trader:
                qs = qs.filter(Q(product__trader=trader) | Q(product__trader_product__trader=trader))
        if self.request.query_params.get('active') == '1':
            qs = qs.filter(is_active=True, ends_at__gt=timezone.now())
        return qs

    def list(self, request, *args, **kwargs):
        active = request.query_params.get('active')
        trader = None
        if request.user.is_authenticated and not request.user.is_staff:
            trader = getattr(request.user, 'trader_application', None)
        if trader:
            cache_key = f"flashsales:trader:{trader.pk}:{'active' if active == '1' else 'all'}"
        else:
            cache_key = 'flashsales:active' if active == '1' else 'flashsales:all'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, FLASH_SALE_CACHE_TTL)
        return response

    def perform_create(self, serializer):
        serializer.save()
        cache.delete_many(['flashsales:active', 'flashsales:all'])


class FlashSaleDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FlashSale.objects.select_related('product__category').prefetch_related('product__images')
    serializer_class = FlashSaleSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsTraderProductOwner()]

    def perform_update(self, serializer):
        serializer.save()
        cache.delete_many(['flashsales:active', 'flashsales:all'])

    def perform_destroy(self, instance):
        instance.delete()
        cache.delete_many(['flashsales:active', 'flashsales:all'])


# ── Product Reviews ──────────────────────────────────────────────────────────

class ProductReviewListCreateView(APIView):
    """
    GET  /api/products/<slug>/reviews/   — list published reviews (public)
    POST /api/products/<slug>/reviews/   — submit a review (authenticated)
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug)
        qs = ProductReview.objects.filter(
            product=product, status='published'
        ).prefetch_related('images').select_related('user').order_by('-created_at')

        star = request.query_params.get('star')
        if star and star.isdigit():
            qs = qs.filter(overall_rating=int(star))

        with_photos = request.query_params.get('with_photos')
        if with_photos == '1':
            qs = qs.filter(images__isnull=False).distinct()

        serializer = ProductReviewSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, slug):
        if request.user.is_staff:
            return Response({'detail': 'Admins cannot submit reviews.'}, status=status.HTTP_403_FORBIDDEN)

        product = get_object_or_404(Product, slug=slug)

        delivered_items = OrderItem.objects.filter(
            product=product,
            order__user=request.user,
            order__status='delivered',
        ).select_related('order')

        try:
            order_id = int(request.data.get('order') or 0)
            order_item_id = int(request.data.get('order_item') or 0)
        except (TypeError, ValueError):
            return Response({'detail': 'A valid delivered order item is required.'}, status=status.HTTP_400_BAD_REQUEST)

        delivered_item = delivered_items.filter(
            order_id=order_id,
            pk=order_item_id,
        ).first() if order_id and order_item_id else None

        if not delivered_item:
            return Response(
                {'detail': 'You can only review products from your delivered orders.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if ProductReview.objects.filter(product=product, user=request.user, order_id=delivered_item.order_id).exists():
            return Response(
                {'detail': 'You have already reviewed this product for this order.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data.copy()

        # Sanitize review text
        raw_text = data.get('review_text', '')
        data['review_text'] = bleach.clean(raw_text, tags=[], strip=True)[:500]

        serializer = ProductReviewSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        review = serializer.save(
            product=product, user=request.user, verified_purchase=True,
            order_id=delivered_item.order_id, order_item_id=delivered_item.id,
        )

        # Save uploaded images from request.FILES
        for img_file in request.FILES.getlist('uploaded_images')[:5]:
            ReviewImage.objects.create(review=review, image=img_file)

        # Recalculate product average rating
        _update_product_rating(product)

        return Response(ProductReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class ProductReviewDetailView(APIView):
    """
    DELETE /api/products/<slug>/reviews/<pk>/  — admin only
    """
    permission_classes = (permissions.IsAdminUser,)

    def delete(self, request, slug, pk):
        product = get_object_or_404(Product, slug=slug)
        review = get_object_or_404(ProductReview, pk=pk, product=product)
        review.delete()
        _update_product_rating(product)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductReviewEligibilityView(APIView):
    """GET /api/products/<slug>/reviews/eligibility/"""
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug)

        delivered_items = OrderItem.objects.filter(
            product=product,
            order__user=request.user,
            order__status='delivered',
        ).select_related('order')
        order_code = request.query_params.get('order_code')
        if order_code:
            delivered_items = delivered_items.filter(order__code=order_code)
            delivered_item = delivered_items.order_by('-order__created_at').first()
        else:
            all_delivered_items = delivered_items
            reviewed_order_ids = ProductReview.objects.filter(
                product=product,
                user=request.user,
                order__isnull=False,
            ).values_list('order_id', flat=True)
            delivered_item = delivered_items.exclude(order_id__in=reviewed_order_ids).order_by('-order__created_at').first()
            if not delivered_item:
                if not all_delivered_items.exists():
                    return Response({'eligible': False, 'reason': 'no_delivered_order'})
                return Response({'eligible': False, 'reason': 'already_reviewed'})

        if not delivered_item:
            return Response({'eligible': False, 'reason': 'no_delivered_order'})

        existing = ProductReview.objects.filter(
            product=product, user=request.user, order=delivered_item.order
        ).first()

        if existing:
            return Response({'eligible': False, 'reason': 'already_reviewed', 'existing_review_id': existing.id})

        return Response({
            'eligible': True,
            'order_id': delivered_item.order_id,
            'order_item_id': delivered_item.id,
            'order_code': delivered_item.order.code,
            'existing_review_id': None,
        })


class ProductRatingSummaryView(APIView):
    """GET /api/products/<slug>/reviews/summary/"""

    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug)
        qs = ProductReview.objects.filter(product=product, status='published')
        total = qs.count()
        breakdown = {}
        for star in range(1, 6):
            breakdown[str(star)] = qs.filter(overall_rating=star).count()
        avg = qs.aggregate(a=Avg('overall_rating'))['a'] or 0
        with_photos = qs.filter(images__isnull=False).distinct().count()
        return Response({
            'average': round(float(avg), 1),
            'total': total,
            'breakdown': breakdown,
            'with_photos': with_photos,
        })


class MyReviewsView(generics.ListAPIView):
    """GET /api/products/reviews/mine/"""
    serializer_class = ProductReviewSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return ProductReview.objects.filter(
            user=self.request.user
        ).select_related('product').prefetch_related('images').order_by('-created_at')


# ── Helpers ──────────────────────────────────────────────────────────────────

def _update_product_rating(product):
    from django.db.models import Avg
    avg = ProductReview.objects.filter(
        product=product, status='published'
    ).aggregate(v=Avg('overall_rating'))['v'] or 0
    product.rating = round(float(avg), 1)
    product.save(update_fields=['rating'])


# ── Share view ───────────────────────────────────────────────────────────────

def ProductShareView(request, slug):
    product = get_object_or_404(Product.objects.select_related('category'), slug=slug)
    image_url = product.image.url if product.image else ''
    description = f'Buy {product.name} from Majo Gadgets for UGX {product.price:,.0f}. Quality gadgets, great value.'
    app_url = f'shopmajo://shop/{product.slug}'
    title = escape(f'{product.name} | Majo Gadgets')
    safe_description = escape(description)
    safe_image = escape(image_url, quote=True)
    safe_app_url = escape(app_url, quote=True)

    html = f'''<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <meta property="og:title" content="{title}">
        <meta property="og:description" content="{safe_description}">
        <meta property="og:type" content="product">
        <meta property="og:url" content="{request.build_absolute_uri()}">
        {f'<meta property="og:image" content="{safe_image}">' if safe_image else ''}
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="{title}">
        <meta name="twitter:description" content="{safe_description}">
        {f'<meta name="twitter:image" content="{safe_image}">' if safe_image else ''}
        <meta http-equiv="refresh" content="0;url={safe_app_url}">
        <title>{title}</title>
    </head>
    <body>
        <p>Opening {escape(product.name)} in Majo Gadgets...</p>
        <p><a href="{safe_app_url}">Open product</a></p>
    </body>
</html>'''
    return HttpResponse(html)
