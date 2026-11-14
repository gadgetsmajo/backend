import bleach
import json
import logging
from html import escape
from uuid import UUID

from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Case, Count, Exists, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, Least
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django_redis.exceptions import ConnectionInterrupted
from redis.exceptions import RedisError
from rest_framework import generics, filters, permissions, status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .pagination import ProductPagination
from .cache import invalidate_category_cache, invalidate_product_cache
from .catalog_sync import sync_product_to_catalog
from .listing import diversify_items, diversify_product_queryset
from .models import Category, CategoryAttribute, Product, ProductImage, ProductVariant, FlashSale, ProductReview, ReviewImage
from .serializers import (
    CategorySerializer, ProductSerializer, ProductImageSerializer,
    FlashSaleSerializer,
    ProductReviewSerializer, RatingSummarySerializer,
)
from .permissions import IsAdminOrProductOwnerOrReadOnly, IsAdminOrReadOnly
from .visibility import public_marketplace_product_filter
from orders.models import OrderItem
from users.models import UserBehaviour


CATEGORY_CACHE_TTL = 60 * 30  # 30 minutes
logger = logging.getLogger(__name__)


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

        if product.is_catalog_anchor:
            return product.trader_offers.filter(
                trader=trader_app,
                review_status='approved',
                is_active=True,
            ).exists()

        if product.trader_id == trader_app.id:
            return True
        return bool(product.trader_product and product.trader_product.trader_id == trader_app.id)


class CategoryListView(generics.ListCreateAPIView):
    queryset = Category.objects.all().annotate(
        product_count=Count('products', distinct=True),
    ).prefetch_related('attributes')
    serializer_class = CategorySerializer
    permission_classes = (IsAdminOrReadOnly,)
    pagination_class = None

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_staff:
            return queryset

        # A visible child must not outlive an inactive parent in the public taxonomy.
        return queryset.filter(is_active=True).exclude(
            parent__is_active=False,
        ).exclude(
            parent__parent__is_active=False,
        )

    def list(self, request, *args, **kwargs):
        cache_key = 'categories:list:v5:admin' if request.user.is_staff else 'categories:list:v5:public'
        try:
            cached = cache.get(cache_key)
        except (ConnectionInterrupted, RedisError):
            logger.exception('Category list cache read failed.')
            cached = None
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        if isinstance(response.data, list):
            by_id = {item['id']: item for item in response.data}
            direct_counts = {item['id']: item['product_count'] for item in response.data}
            for descendant in response.data:
                count = direct_counts[descendant['id']]
                parent_id = descendant['parent_id']
                ancestors = []
                visited = {descendant['id']}
                has_cycle = False
                while parent_id is not None:
                    if parent_id in visited:
                        logger.error(
                            'Category hierarchy cycle detected while counting products for category %s.',
                            descendant['id'],
                        )
                        has_cycle = True
                        break
                    visited.add(parent_id)
                    parent = by_id.get(parent_id)
                    if parent is None:
                        break
                    ancestors.append(parent)
                    parent_id = parent['parent_id']
                if not has_cycle:
                    for ancestor in ancestors:
                        ancestor['product_count'] += count
        try:
            cache_data = json.loads(JSONRenderer().render(response.data))
            cache.set(cache_key, cache_data, CATEGORY_CACHE_TTL)
        except (ConnectionInterrupted, RedisError):
            logger.exception('Category list cache write failed.')
        return response

    def perform_create(self, serializer):
        serializer.save()
        self._invalidate_category_cache()

    @staticmethod
    def _invalidate_category_cache():
        invalidate_category_cache()


class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = (IsAdminOrReadOnly,)

    def get_queryset(self):
        queryset = super().get_queryset().annotate(product_count=Count('products', distinct=True))
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(is_active=True)

    def perform_update(self, serializer):
        serializer.save()
        CategoryListView._invalidate_category_cache()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=('is_active',))
        CategoryListView._invalidate_category_cache()


def annotate_catalog_offer_metrics(queryset):
    from traders.models import TraderProduct

    offers = TraderProduct.objects.filter(
        Q(listing_product_id=OuterRef('pk'))
        | Q(catalog_product__public_product_id=OuterRef('pk'))
        | Q(legacy_public_product__pk=OuterRef('pk')),
        is_active=True,
        review_status='approved',
        stock__gt=0,
        trader__status='approved',
        trader__is_visible=True,
        trader__is_closed=False,
    )
    lowest_price = offers.order_by('price', 'pk').values('price')[:1]
    total_stock = offers.values('listing_product_id').annotate(
        total=Sum('stock'),
    ).values('total')[:1]
    return queryset.annotate(
        _has_available_offer=Exists(offers),
        _marketplace_price=Case(
            When(
                is_catalog_anchor=True,
                stock__gt=0,
                price__gt=0,
                then=Least(
                    F('price'),
                    Coalesce(Subquery(lowest_price), F('price')),
                ),
            ),
            When(
                is_catalog_anchor=True,
                then=Coalesce(Subquery(lowest_price), F('price')),
            ),
            default=F('price'),
        ),
        _marketplace_stock=Case(
            When(
                is_catalog_anchor=True,
                then=Coalesce(Subquery(total_stock), F('stock')),
            ),
            default=F('stock'),
            output_field=IntegerField(),
        ),
    )


class ProductListView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = (IsAdminOrReadOnly,)
    pagination_class = ProductPagination
    filter_backends = (filters.SearchFilter, filters.OrderingFilter)
    search_fields = (
        'name', 'brand', 'category__name', 'category__parent__name',
        'category__parent__parent__name', 'specifications', 'variants__options',
    )
    ordering_fields = ('price', 'rating', 'created_at')

    def get_queryset(self):
        from traders.models import TraderInventoryItem, TraderProduct

        variant_queryset = ProductVariant.objects.select_related(
            'product__trader', 'product__trader_product__trader',
        ).annotate(
            sold_quantity=Sum('order_items__quantity'),
            has_inventory_item=Exists(
                TraderInventoryItem.objects.filter(variant_id=OuterRef('pk')),
            ),
        )
        qs = Product.objects.all().select_related(
            'category', 'trader', 'trader_product__trader',
            'catalog_product__category', 'trader_product__catalog_product',
        ).prefetch_related(
            'images',
            Prefetch('variants', queryset=variant_queryset),
            Prefetch(
                'trader_offers',
                queryset=TraderProduct.objects.filter(
                    is_active=True,
                    review_status='approved',
                    stock__gt=0,
                    trader__status='approved',
                    trader__is_visible=True,
                    trader__is_closed=False,
                ).select_related('trader'),
            ),
        )
        qs = qs.annotate(
            _storefront_updated_at=Coalesce(
                'catalog_product__updated_at',
                'created_at',
            ),
        )
        qs = annotate_catalog_offer_metrics(qs)
        if not self.request.user.is_staff:
            qs = qs.filter(
                is_active=True,
                review_status='approved',
            ).filter(public_marketplace_product_filter())
            qs = qs.filter(
                Q(catalog_product__isnull=True) | Q(is_catalog_anchor=True),
                Q(is_catalog_anchor=False)
                | Q(_has_available_offer=True)
                | Q(stock__gt=0, price__gt=0),
            )
        category = self.request.query_params.get('category')
        if category:
            selected = Category.objects.filter(slug=category, is_active=True).first()
            if selected is None:
                return qs.none()
            ancestor = selected.parent
            while ancestor:
                if not ancestor.is_active:
                    return qs.none()
                ancestor = ancestor.parent
            descendants = [selected.pk]
            pending = [selected.pk]
            while pending:
                child_ids = list(Category.objects.filter(
                    parent_id__in=pending,
                    is_active=True,
                ).values_list('pk', flat=True))
                descendants.extend(child_ids)
                pending = child_ids
            qs = qs.filter(category_id__in=descendants)
        price_min = self.request.query_params.get('price_min')
        if price_min:
            qs = qs.filter(_marketplace_price__gte=price_min)
        price_max = self.request.query_params.get('price_max')
        if price_max:
            qs = qs.filter(_marketplace_price__lte=price_max)
        brand = self.request.query_params.get('brand')
        if brand:
            qs = qs.filter(brand__icontains=brand.strip())
        available = self.request.query_params.get('available')
        if available == 'true':
            qs = qs.filter(
                Q(is_catalog_anchor=False, stock__gt=0)
                | Q(_has_available_offer=True)
                | Q(is_catalog_anchor=True, stock__gt=0, price__gt=0)
            )
        min_rating = self.request.query_params.get('min_rating')
        if min_rating:
            qs = qs.filter(rating__gte=min_rating)
        filterable_attributes = {}
        for key, is_variant in CategoryAttribute.objects.filter(is_filterable=True).values_list('key', 'is_variant'):
            filterable_attributes[key] = filterable_attributes.get(key, False) or is_variant
        for parameter, value in self.request.query_params.items():
            if parameter.startswith('attr_'):
                key = parameter[5:]
                if key in filterable_attributes and value:
                    spec_filter = Q(**{f'specifications__{key}__icontains': value})
                    if filterable_attributes[key]:
                        variant_filter = Q(**{
                            f'variants__options__{key}__iexact': value,
                            'variants__is_active': True,
                            'variants__stock__gt': 0,
                        })
                        variant_filter |= Q(**{
                            f'trader_offers__variants__options__{key}__iexact': value,
                            'trader_offers__variants__is_active': True,
                            'trader_offers__variants__stock__gt': 0,
                            'trader_offers__is_active': True,
                            'trader_offers__review_status': 'approved',
                        })
                        qs = qs.filter(spec_filter | variant_filter).distinct()
                    else:
                        qs = qs.filter(spec_filter)
        seller_uuid = self.request.query_params.get('seller')
        if seller_uuid:
            try:
                seller_uuid = UUID(seller_uuid)
            except ValueError:
                visible_seller = Q(
                    trader__business_name__icontains=seller_uuid,
                    trader__status='approved',
                    trader__is_visible=True,
                    trader__is_closed=False,
                )
                visible_seller |= Q(
                    trader_product__trader__business_name__icontains=seller_uuid,
                    trader_product__trader__status='approved',
                    trader_product__trader__is_visible=True,
                    trader_product__trader__is_closed=False,
                )
                visible_seller |= Q(
                    trader_offers__trader__business_name__icontains=seller_uuid,
                    trader_offers__trader__status='approved',
                    trader_offers__trader__is_visible=True,
                    trader_offers__trader__is_closed=False,
                )
            else:
                visible_seller = Q(trader__uuid=seller_uuid, trader__status='approved', trader__is_visible=True, trader__is_closed=False)
                visible_seller |= Q(trader_product__trader__uuid=seller_uuid, trader_product__trader__status='approved', trader_product__trader__is_visible=True, trader_product__trader__is_closed=False)
                visible_seller |= Q(trader_offers__trader__uuid=seller_uuid, trader_offers__trader__status='approved', trader_offers__trader__is_visible=True, trader_offers__trader__is_closed=False)
            qs = qs.filter(visible_seller)
        if self.request.query_params.get('top_bought') == 'true':
            qs = qs.annotate(
                bought_quantity=Coalesce(
                    Sum('orderitem__quantity', filter=Q(orderitem__order__status='delivered')),
                    Value(0),
                    output_field=IntegerField(),
                )
            ).filter(bought_quantity__gt=0)
            ordering = ('-bought_quantity', '-created_at', '-pk')
        else:
            ordering = ('-_storefront_updated_at', '-created_at', '-pk')
        qs = qs.order_by(*ordering)
        if not self.request.query_params.get('ordering') and not self.request.user.is_staff:
            qs = diversify_product_queryset(qs, ordering)
        return qs

    def perform_create(self, serializer):
        cover = self.request.FILES.get('image')
        product = serializer.save(**(({'image': cover}) if cover else {}))
        for i, img in enumerate(self.request.FILES.getlist('images')):
            ProductImage.objects.create(product=product, image=img, order=i)
        if self.request.user.is_staff:
            sync_product_to_catalog(product)
        invalidate_product_cache(product.pk)
        invalidate_category_cache()


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.all().select_related(
        'category', 'trader', 'trader_product__trader',
        'catalog_product__category', 'trader_product__catalog_product',
    ).prefetch_related('images', 'variants')
    serializer_class = ProductSerializer
    permission_classes = (IsAdminOrProductOwnerOrReadOnly,)

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            trader = getattr(self.request.user, 'trader_application', None)
            if trader is None:
                return queryset.filter(
                    is_active=True,
                    review_status='approved',
                ).filter(public_marketplace_product_filter())
            queryset = queryset.filter(
                Q(is_active=True, review_status='approved')
                | Q(trader_id=trader.pk)
                | Q(trader_product__trader_id=trader.pk)
            )
        return queryset

    def perform_update(self, serializer):
        cover = self.request.FILES.get('image')
        product = serializer.save(**(({'image': cover}) if cover else {}))
        submit_for_review = self.request.data.get('submit_for_review')
        if product.review_status in ('draft', 'rejected', 'changes_required') and submit_for_review is not None:
            is_submitting = str(submit_for_review).strip().lower() in {'true', '1', 'yes'}
            product.review_status = 'pending_review' if is_submitting else 'draft'
            product.review_note = ''
            product.is_active = False
            product.save(update_fields=('review_status', 'review_note', 'is_active'))
        if product.trader_product_id:
            trader_product = product.trader_product
            trader_product.name = product.name
            trader_product.brand = product.brand
            trader_product.condition = product.condition
            trader_product.tags = product.tags
            trader_product.specifications = product.specifications
            trader_product.short_description = product.short_description
            trader_product.long_description = product.long_description
            trader_product.description = product.short_description
            trader_product.price = product.price
            trader_product.original_price = product.original_price
            trader_product.delivery_fee = product.delivery_fee
            trader_product.stock = product.stock
            trader_product.category = product.category
            trader_product.image = product.image
            trader_product.is_featured = product.is_featured
            trader_product.is_new_deal = product.is_new_deal
            trader_product.is_active = product.is_active
            trader_product.save(update_fields=(
                'name', 'brand', 'condition', 'tags', 'specifications',
                'short_description', 'long_description', 'description',
                'price', 'original_price', 'delivery_fee', 'stock', 'category',
                'image', 'is_featured', 'is_new_deal', 'is_active', 'updated_at',
            ))
        files = self.request.FILES.getlist('images')
        if files:
            start = product.images.count()
            for i, img in enumerate(files):
                ProductImage.objects.create(product=product, image=img, order=start + i)
        if self.request.user.is_staff:
            sync_product_to_catalog(product)
        invalidate_product_cache(product.pk)
        invalidate_category_cache()

    def perform_destroy(self, instance):
        product_id = instance.pk
        instance.delete()
        invalidate_product_cache(product_id)
        invalidate_category_cache()


class ProductReviewStatusView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    @transaction.atomic
    def post(self, request, pk):
        product = get_object_or_404(
            Product.objects.select_related('trader', 'trader_product__trader'),
            pk=pk,
        )
        review_status = request.data.get('review_status')
        allowed_statuses = {'approved', 'rejected', 'changes_required', 'disabled', 'archived'}
        if review_status not in allowed_statuses:
            return Response(
                {'review_status': 'Choose an allowed review status.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        review_note = str(request.data.get('review_note', '')).strip()
        if review_status in {'rejected', 'changes_required'} and not review_note:
            return Response(
                {'review_note': 'Provide a reason for this decision.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product.review_status = review_status
        product.review_note = review_note if review_status in {'rejected', 'changes_required'} else ''
        if review_status == 'approved':
            trader = product.trader or (
                product.trader_product.trader if product.trader_product_id else None
            )
            trader_product_active = (
                product.trader_product.is_active if product.trader_product_id else True
            )
            product.is_active = bool(
                trader_product_active
                and (not trader or (trader.is_visible and not trader.is_closed))
            )
        else:
            product.is_active = False

        product.save(update_fields=('review_status', 'review_note', 'is_active'))
        catalog_product = sync_product_to_catalog(product, approve_existing=True)
        if product.trader_product_id:
            offer = product.trader_product
            offer.review_status = review_status
            offer.review_note = product.review_note
            offer.is_active = product.is_active
            update_fields = ['review_status', 'review_note', 'is_active', 'updated_at']
            if review_status == 'approved':
                from .catalog_sync import ensure_catalog_public_product

                public_product = ensure_catalog_public_product(catalog_product)
                offer.catalog_product = catalog_product
                offer.listing_product = public_product
                update_fields.extend(('catalog_product', 'listing_product'))
            offer.save(update_fields=update_fields)
        invalidate_product_cache(product.pk)
        invalidate_category_cache()
        return Response(ProductSerializer(product, context={'request': request}).data)


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
    queryset = Product.objects.all().select_related('category', 'trader', 'trader_product__trader').prefetch_related('variants')
    serializer_class = ProductSerializer
    permission_classes = (IsAdminOrReadOnly,)
    lookup_field = 'slug'
    lookup_url_kwarg = 'slug'

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(
                is_active=True,
                review_status='approved',
            ).filter(public_marketplace_product_filter())
        return queryset

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
    from traders.models import TraderProduct

    qs = Product.objects.filter(
        is_active=True,
        review_status='approved',
    ).filter(
        public_marketplace_product_filter(),
    ).select_related('category').prefetch_related(
        'images',
        'variants',
        Prefetch(
            'trader_offers',
            queryset=TraderProduct.objects.filter(
                is_active=True,
                review_status='approved',
                stock__gt=0,
                trader__status='approved',
                trader__is_visible=True,
                trader__is_closed=False,
            ).select_related('trader'),
        ),
    )
    qs = annotate_catalog_offer_metrics(qs).annotate(
        _storefront_updated_at=Coalesce(
            'catalog_product__updated_at',
            'created_at',
        ),
    ).filter(
        Q(catalog_product__isnull=True) | Q(is_catalog_anchor=True),
        Q(is_catalog_anchor=False)
        | Q(_has_available_offer=True)
        | Q(stock__gt=0, price__gt=0),
    ).order_by('-rating', '-_storefront_updated_at', '-created_at')

    if not user or not user.is_authenticated:
        return diversify_items(list(qs[:limit]))

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
        return diversify_items(list(qs.exclude(pk__in=seen_product_ids)[:limit]))

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
    return diversify_items([product for _, product in ranked[:limit]])


# ── Flash Sales ─────────────────────────────────────────────────────────────

class FlashSaleListCreateView(generics.ListCreateAPIView):
    serializer_class = FlashSaleSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsTraderProductOwner()]

    def get_queryset(self):
        from django.utils import timezone
        from traders.models import TraderProduct

        qs = FlashSale.objects.select_related(
            'product__category', 'product__trader',
            'product__trader_product__trader', 'product__catalog_product__category',
        ).prefetch_related(
            'product__images',
            Prefetch(
                'product__trader_offers',
                queryset=TraderProduct.objects.filter(
                    is_active=True,
                    review_status='approved',
                    stock__gt=0,
                    trader__status='approved',
                    trader__is_visible=True,
                    trader__is_closed=False,
                ).select_related('trader'),
            ),
        )
        if self.request.method == 'GET':
            qs = qs.filter(
                product__is_active=True,
                product__review_status='approved',
            ).filter(public_marketplace_product_filter('product__'))
        if self.request.user.is_authenticated and not self.request.user.is_staff:
            trader = getattr(self.request.user, 'trader_application', None)
            if trader:
                qs = qs.filter(
                    Q(product__trader=trader)
                    | Q(product__trader_product__trader=trader)
                    | Q(
                        product__is_catalog_anchor=True,
                        product__trader_offers__trader=trader,
                        product__trader_offers__review_status='approved',
                        product__trader_offers__is_active=True,
                    )
                ).distinct()
        if self.request.query_params.get('active') == '1':
            qs = qs.filter(is_active=True, ends_at__gt=timezone.now())
            qs = diversify_items(
                qs.order_by('-created_at', '-pk'),
                product_getter=lambda sale: sale.product,
            )
        return qs

    def perform_create(self, serializer):
        serializer.save()


class FlashSaleDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FlashSale.objects.select_related('product__category').prefetch_related('product__images')
    serializer_class = FlashSaleSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsTraderProductOwner()]

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()


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
        qs = _reviews_for_product(product).filter(
            status='published',
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

        delivered_items = _order_items_for_product(product).filter(
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

        if _reviews_for_product(product).filter(
            user=request.user,
            order_id=delivered_item.order_id,
        ).exists():
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
        review = get_object_or_404(_reviews_for_product(product), pk=pk)
        review.delete()
        _update_product_rating(product)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductReviewEligibilityView(APIView):
    """GET /api/products/<slug>/reviews/eligibility/"""
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug)

        delivered_items = _order_items_for_product(product).filter(
            order__user=request.user,
            order__status='delivered',
        ).select_related('order')
        order_code = request.query_params.get('order_code')
        if order_code:
            delivered_items = delivered_items.filter(order__code=order_code)
            delivered_item = delivered_items.order_by('-order__created_at').first()
        else:
            all_delivered_items = delivered_items
            reviewed_order_ids = _reviews_for_product(product).filter(
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

        existing = _reviews_for_product(product).filter(
            user=request.user, order=delivered_item.order,
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
        qs = _reviews_for_product(product).filter(status='published')
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
    avg = _reviews_for_product(product).filter(
        status='published',
    ).aggregate(v=Avg('overall_rating'))['v'] or 0
    rating = round(float(avg), 1)
    if product.is_catalog_anchor and product.catalog_product_id:
        Product.objects.filter(
            catalog_product_id=product.catalog_product_id,
            is_catalog_anchor=True,
        ).update(rating=rating)
    else:
        product.rating = rating
        product.save(update_fields=['rating'])


def _reviews_for_product(product):
    queryset = ProductReview.objects.all()
    if product.is_catalog_anchor and product.catalog_product_id:
        return queryset.filter(
            Q(product=product)
            | Q(product__catalog_product_id=product.catalog_product_id)
        )
    return queryset.filter(product=product)


def _order_items_for_product(product):
    queryset = OrderItem.objects.all()
    if product.is_catalog_anchor and product.catalog_product_id:
        return queryset.filter(
            Q(product=product)
            | Q(product__catalog_product_id=product.catalog_product_id)
        )
    return queryset.filter(product=product)


# ── Share view ───────────────────────────────────────────────────────────────

def ProductShareView(request, slug):
    product = get_object_or_404(
        Product.objects.select_related('category').filter(
            is_active=True,
            review_status='approved',
        ).filter(public_marketplace_product_filter()),
        slug=slug,
    )
    image_url = product.image.url if product.image else ''
    description = f'Shop {product.name} on Majo Gadgets for UGX {product.price:,.0f}.'
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
