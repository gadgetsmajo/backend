from datetime import timedelta

from django.db.models import Avg, Count, F, Q
from orders.models import OrderItem
from products.models import Product, ProductReview
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from .models import TraderApplication, TraderFollower, TraderProduct, TraderSale, TraderExpense, TraderOrderItem, TraderInventoryItem, TraderStockMovement
from .serializers import (
    TraderApplicationSerializer, TraderApplicationAdminSerializer,
    TraderProductSerializer, TraderSaleSerializer, TraderExpenseSerializer,
    TraderOrderItemSerializer, TraderInventoryItemSerializer, TraderStockMovementSerializer,
)


def _get_trader_by_uuid(uuid_str):
    try:
        return TraderApplication.objects.get(uuid=uuid_str, status='approved')
    except TraderApplication.DoesNotExist:
        return None


class IsTraderOwner(permissions.BasePermission):
    """Allow access only if the authenticated user owns the trader account (matched by email)."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        uuid_str = view.kwargs.get('trader_uuid')
        trader = _get_trader_by_uuid(uuid_str)
        if not trader:
            return False
        return trader.email == request.user.email or request.user.is_staff


# ── Public: submit application ────────────────────────────────────────────────

class TraderApplicationCreateView(generics.CreateAPIView):
    serializer_class = TraderApplicationSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def create(self, request, *args, **kwargs):
        # If user already has an application, block re-submission unless rejected
        existing = TraderApplication.objects.filter(user=request.user).order_by('-created_at').first()
        if not existing:
            existing = TraderApplication.objects.filter(email=request.user.email).order_by('-created_at').first()
        if existing and existing.status in ('pending', 'approved'):
            return Response(
                {'detail': f'You already have a {existing.status} application.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ── Trader: get own profile by UUID ──────────────────────────────────────────

class TraderProfileView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(TraderApplicationAdminSerializer(trader).data)


class TraderMeView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        applicant = TraderApplication.objects.filter(user=request.user).order_by('-created_at').first()
        if not applicant:
            # fallback: match by email for legacy applications
            applicant = TraderApplication.objects.filter(email=request.user.email).order_by('-created_at').first()
        if not applicant:
            # Some admin/session checks poll this endpoint to decide whether the user
            # has a trader account. Treat a missing application as a valid, empty state
            # instead of an error so the UI can gracefully handle "not a trader".
            return Response(None, status=status.HTTP_200_OK)

        return Response({
            'id': applicant.id,
            'uuid': str(applicant.uuid),
            'business_name': applicant.business_name,
            'status': applicant.status,
            'email': applicant.email,
            'full_name': applicant.full_name,
        })


class PublicTraderProfileView(APIView):
    def get_permissions(self):
        if self.request.method in ('GET', 'OPTIONS'):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_trader(self, trader_uuid):
        return TraderApplication.objects.filter(
            uuid=trader_uuid,
            status='approved',
            is_visible=True,
            is_closed=False,
        ).first()

    def get(self, request, trader_uuid):
        trader = self.get_trader(trader_uuid)
        if not trader:
            return Response({'detail': 'Seller not found.'}, status=status.HTTP_404_NOT_FOUND)

        seller_products = Q(product__trader=trader) | Q(product__trader_product__trader=trader)
        review_stats = ProductReview.objects.filter(
            seller_products,
            status='published',
        ).aggregate(
            customer_rating=Avg('overall_rating'),
            quality_rating=Avg('product_quality_rating'),
            review_count=Count('id'),
            quality_review_count=Count('product_quality_rating'),
        )

        order_items = OrderItem.objects.filter(
            Q(product__trader=trader) | Q(product__trader_product__trader=trader)
        ).filter(order__status__in=('delivered', 'cancelled'))
        total_order_items = order_items.count()
        cancelled_items = order_items.filter(order__status='cancelled').count()
        cancellation_rate = round(cancelled_items * 100 / total_order_items, 1) if total_order_items else None

        shipping = TraderOrderItem.objects.filter(trader=trader, ready_at__isnull=False).aggregate(
            total=Count('id'),
            within_48_hours=Count(
                'id',
                filter=Q(ready_at__lte=F('order_item__order__created_at') + timedelta(hours=48)),
            ),
        )
        shipping_speed_score = (
            round(shipping['within_48_hours'] * 100 / shipping['total'], 1)
            if shipping['total'] else None
        )

        customer_rating = float(review_stats['customer_rating']) if review_stats['customer_rating'] is not None else None
        quality_rating = float(review_stats['quality_rating']) if review_stats['quality_rating'] is not None else None
        score_components = [
            rating * 20 for rating in (customer_rating, quality_rating) if rating is not None
        ]
        if shipping_speed_score is not None:
            score_components.append(shipping_speed_score)
        if cancellation_rate is not None:
            score_components.append(100 - cancellation_rate)

        is_following = request.user.is_authenticated and TraderFollower.objects.filter(
            trader=trader, user=request.user
        ).exists()
        return Response({
            'uuid': str(trader.uuid),
            'business_name': trader.business_name,
            'location': trader.location,
            'district': trader.district,
            'bio': trader.bio,
            'is_verified': True,
            'follower_count': trader.follower_records.count(),
            'is_following': is_following,
            'customer_rating': customer_rating,
            'review_count': review_stats['review_count'],
            'quality_rating': quality_rating,
            'quality_review_count': review_stats['quality_review_count'],
            'shipping_speed_score': shipping_speed_score,
            'shipping_sample_count': shipping['total'],
            'cancellation_rate': cancellation_rate,
            'order_item_count': total_order_items,
            'seller_score': round(sum(score_components) / len(score_components), 1) if score_components else None,
        })

    def post(self, request, trader_uuid):
        trader = self.get_trader(trader_uuid)
        if not trader:
            return Response({'detail': 'Seller not found.'}, status=status.HTTP_404_NOT_FOUND)
        _, created = TraderFollower.objects.get_or_create(trader=trader, user=request.user)
        return Response({'following': True, 'follower_count': trader.follower_records.count()}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, trader_uuid):
        trader = self.get_trader(trader_uuid)
        if not trader:
            return Response({'detail': 'Seller not found.'}, status=status.HTTP_404_NOT_FOUND)
        TraderFollower.objects.filter(trader=trader, user=request.user).delete()
        return Response({'following': False, 'follower_count': trader.follower_records.count()})


# ── Trader: dashboard stats ───────────────────────────────────────────────────

class TraderDashboardView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)

        sales = TraderSale.objects.filter(trader=trader)
        expenses = TraderExpense.objects.filter(trader=trader)
        products = TraderProduct.objects.filter(trader=trader)

        total_revenue = sum(s.total for s in sales)
        total_expenses = sum(e.amount for e in expenses)
        net_profit = total_revenue - total_expenses

        from django.utils import timezone as tz
        today = tz.now().date()
        today_sales = sales.filter(created_at__date=today)
        today_revenue = sum(s.total for s in today_sales)

        return Response({
            'total_revenue': float(total_revenue),
            'total_expenses': float(total_expenses),
            'net_profit': float(net_profit),
            'today_revenue': float(today_revenue),
            'today_orders': today_sales.count(),
            'total_products': products.count(),
            'active_products': products.filter(is_active=True).count(),
            'total_sales': sales.count(),
        })


# ── Trader: products ──────────────────────────────────────────────────────────

def _sync_to_product(trader_product):
    from products.models import Product
    from django.core.cache import cache
    product, _ = Product.objects.update_or_create(
        trader_product=trader_product,
        defaults={
            'trader': trader_product.trader,
            'name': trader_product.name,
            'short_description': trader_product.short_description or trader_product.description,
            'long_description': trader_product.long_description,
            'price': trader_product.price,
            'original_price': trader_product.original_price,
            'delivery_fee': trader_product.delivery_fee,
            'stock': trader_product.stock,
            'category': trader_product.category,
            'image': trader_product.image,
            'is_active': trader_product.is_active and trader_product.trader.is_visible,
            'is_featured': trader_product.is_featured,
            'is_new_deal': trader_product.is_new_deal,
        },
    )
    cache.delete('products:list')
    cache.delete(f'products:detail:{product.pk}')
    return product


class TraderProductListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        products = TraderProduct.objects.filter(trader=trader)
        return Response(TraderProductSerializer(products, many=True).data)

    def post(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = TraderProductSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image_file = request.FILES.get('image')
        category_id = request.data.get('category_id')
        extra = {'image': image_file} if image_file else {}
        if category_id:
            from products.models import Category
            try:
                extra['category'] = Category.objects.get(pk=category_id)
            except Category.DoesNotExist:
                pass
        tp = serializer.save(trader=trader, **extra)
        _sync_to_product(tp)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TraderProductDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def _get(self, trader_uuid, product_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return None, None
        try:
            product = TraderProduct.objects.get(uuid=product_uuid, trader=trader)
        except TraderProduct.DoesNotExist:
            return trader, None
        return trader, product

    def get(self, request, trader_uuid, product_uuid):
        trader, product = self._get(trader_uuid, product_uuid)
        if not trader or not product:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(TraderProductSerializer(product).data)

    def patch(self, request, trader_uuid, product_uuid):
        trader, product = self._get(trader_uuid, product_uuid)
        if not trader or not product:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = TraderProductSerializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        image_file = request.FILES.get('image')
        category_id = request.data.get('category_id')
        extra = {'image': image_file} if image_file else {}
        if category_id:
            from products.models import Category
            try:
                extra['category'] = Category.objects.get(pk=category_id)
            except Category.DoesNotExist:
                pass
        tp = serializer.save(**extra)
        _sync_to_product(tp)
        return Response(serializer.data)

    def delete(self, request, trader_uuid, product_uuid):
        trader, product = self._get(trader_uuid, product_uuid)
        if not trader or not product:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        from products.models import Product
        from django.core.cache import cache
        pub = Product.objects.filter(trader_product=product).first()
        if pub:
            pub.is_active = False
            pub.save(update_fields=['is_active'])
            cache.delete('products:list')
            cache.delete(f'products:detail:{pub.pk}')
        product.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Trader: sales ─────────────────────────────────────────────────────────────

class TraderSaleListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(TraderSaleSerializer(trader.sales.all(), many=True).data)

    def post(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        # auto-compute total if not provided
        if 'total' not in data:
            try:
                data['total'] = float(data['unit_price']) * int(data['quantity'])
            except Exception:
                pass
        serializer = TraderSaleSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save(trader=trader)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ── Trader: expenses ──────────────────────────────────────────────────────────

class TraderExpenseListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(TraderExpenseSerializer(trader.expenses.all(), many=True).data)

    def post(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = TraderExpenseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(trader=trader)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ── Admin: list + filter ──────────────────────────────────────────────────────

class AdminTraderListView(generics.ListAPIView):
    serializer_class = TraderApplicationAdminSerializer
    permission_classes = (permissions.IsAdminUser,)

    def get_queryset(self):
        qs = TraderApplication.objects.select_related('reviewed_by', 'user')
        s = self.request.query_params.get('status')
        if s:
            qs = qs.filter(status=s)
        return qs


class AdminTraderDetailView(generics.RetrieveAPIView):
    queryset = TraderApplication.objects.select_related('reviewed_by', 'user')
    serializer_class = TraderApplicationAdminSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Admin: approve ────────────────────────────────────────────────────────────

class AdminTraderApproveView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, pk):
        try:
            app = TraderApplication.objects.get(pk=pk)
        except TraderApplication.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if app.status == 'approved':
            return Response({'detail': 'Already approved.'}, status=status.HTTP_400_BAD_REQUEST)

        app.status = 'approved'
        app.admin_note = request.data.get('admin_note', '')
        app.reviewed_by = request.user
        app.reviewed_at = timezone.now()
        app.save()

        # Email notification
        try:
            from users.emails import send_trader_approved_email
            send_trader_approved_email(app.full_name, app.email, app.business_name, str(app.uuid))
        except Exception:
            pass

        # Push notification (if trader has a linked user account)
        if app.user:
            try:
                from users.models import Notification
                Notification.objects.create(
                    user=app.user,
                    type='system',
                    title='Your trader application is approved! 🎉',
                    body=f'Congratulations! {app.business_name} has been approved. Open your trader portal to start selling.',
                )
            except Exception:
                pass

        return Response(TraderApplicationAdminSerializer(app).data)


# ── Admin: reject ─────────────────────────────────────────────────────────────

class AdminTraderRejectView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, pk):
        try:
            app = TraderApplication.objects.get(pk=pk)
        except TraderApplication.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('admin_note', '').strip()
        if not reason:
            return Response({'detail': 'A rejection reason is required.'}, status=status.HTTP_400_BAD_REQUEST)

        app.status = 'rejected'
        app.admin_note = reason
        app.reviewed_by = request.user
        app.reviewed_at = timezone.now()
        app.save()
        return Response(TraderApplicationAdminSerializer(app).data)


# ── Trader: account management ───────────────────────────────────────────────

# ── Trader: inventory ────────────────────────────────────────────────────────

class TraderInventoryListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader or (trader.email != request.user.email and not request.user.is_staff):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        items = TraderInventoryItem.objects.filter(trader=trader).select_related('product')
        return Response(TraderInventoryItemSerializer(items, many=True).data)

    def post(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader or (trader.email != request.user.email and not request.user.is_staff):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        product_id = request.data.get('product')
        try:
            product = TraderProduct.objects.get(pk=product_id, trader=trader)
        except TraderProduct.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_400_BAD_REQUEST)
        item, created = TraderInventoryItem.objects.get_or_create(
            trader=trader, product=product,
            defaults={
                'quantity': int(request.data.get('quantity', 0)),
                'cost_price': request.data.get('cost_price', 0),
                'location': request.data.get('location', ''),
                'note': request.data.get('note', ''),
            }
        )
        if not created:
            return Response({'detail': 'Product already in inventory.'}, status=status.HTTP_400_BAD_REQUEST)
        product.stock = item.quantity
        product.save(update_fields=['stock'])
        _sync_to_product(product)
        return Response(TraderInventoryItemSerializer(item).data, status=status.HTTP_201_CREATED)


class TraderInventoryItemDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def _get(self, trader_uuid, pk, user):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader or (trader.email != user.email and not user.is_staff):
            return None, None
        try:
            return trader, TraderInventoryItem.objects.select_related('product').get(pk=pk, trader=trader)
        except TraderInventoryItem.DoesNotExist:
            return trader, None

    def patch(self, request, trader_uuid, pk):
        trader, item = self._get(trader_uuid, pk, request.user)
        if not item:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        for field in ('cost_price', 'location', 'note'):
            if field in request.data:
                setattr(item, field, request.data[field])
        item.save()
        return Response(TraderInventoryItemSerializer(item).data)

    def delete(self, request, trader_uuid, pk):
        trader, item = self._get(trader_uuid, pk, request.user)
        if not item:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TraderStockMovementView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, trader_uuid, pk):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader or (trader.email != request.user.email and not request.user.is_staff):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            item = TraderInventoryItem.objects.select_related('product').get(pk=pk, trader=trader)
        except TraderInventoryItem.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        mv_type = request.data.get('type')
        if mv_type not in ('in', 'out', 'adjust', 'return'):
            return Response({'detail': 'Invalid type.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            qty = int(request.data.get('quantity', 0))
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid quantity.'}, status=status.HTTP_400_BAD_REQUEST)
        signed_qty = qty if mv_type in ('in', 'return') else (-abs(qty) if mv_type == 'out' else qty)
        TraderStockMovement.objects.create(
            trader=trader, item=item, type=mv_type,
            quantity=signed_qty, note=request.data.get('note', '')
        )
        item.quantity = max(0, item.quantity + signed_qty)
        item.save(update_fields=['quantity', 'updated_at'])
        item.product.stock = max(0, item.product.stock + signed_qty)
        item.product.save(update_fields=['stock'])
        _sync_to_product(item.product)
        return Response(TraderInventoryItemSerializer(item).data)


class TraderAccountView(APIView):
    """
    GET  /api/traders/<uuid>/account/  — full profile
    PATCH /api/traders/<uuid>/account/ — update business_name, bio, logo, is_visible
    DELETE /api/traders/<uuid>/account/ — delete shop permanently
    """
    permission_classes = (permissions.IsAuthenticated,)

    def _trader(self, trader_uuid, user):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return None
        if trader.email != user.email and not user.is_staff:
            return None
        return trader

    def get(self, request, trader_uuid):
        trader = self._trader(trader_uuid, request.user)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(TraderApplicationAdminSerializer(trader).data)

    def patch(self, request, trader_uuid):
        trader = self._trader(trader_uuid, request.user)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        allowed = ('business_name', 'bio', 'phone', 'location', 'district', 'website', 'is_visible', 'is_closed')
        for field in allowed:
            if field in request.data:
                val = request.data[field]
                if field in ('is_visible', 'is_closed'):
                    val = str(val).lower() in ('true', '1', 'yes')
                setattr(trader, field, val)

        logo_file = request.FILES.get('logo')
        if logo_file:
            trader.logo = logo_file

        trader.save()

        # Sync product visibility when is_visible changes
        if 'is_visible' in request.data:
            from products.models import Product
            Product.objects.filter(trader=trader).update(is_active=trader.is_visible)

        return Response(TraderApplicationAdminSerializer(trader).data)

    def delete(self, request, trader_uuid):
        trader = self._trader(trader_uuid, request.user)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        confirm = request.data.get('confirm', '')
        if confirm != 'DELETE':
            return Response({'detail': 'Send confirm=DELETE to permanently delete your shop.'}, status=status.HTTP_400_BAD_REQUEST)
        # Hide all products first
        from products.models import Product
        Product.objects.filter(trader=trader).update(is_active=False)
        trader.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Trader: orders ────────────────────────────────────────────────────────────

class TraderOrderListView(APIView):
    """
    GET  /api/traders/<uuid>/orders/
    Returns all TraderOrderItem records for this trader, auto-creating them
    for any new order items that belong to their products.
    """
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)

        # Find all order items whose product belongs to this trader's store products
        from orders.models import OrderItem
        from products.models import Product
        trader_product_ids = Product.objects.filter(
            Q(trader=trader) | Q(trader_product__trader=trader)
        ).values_list('id', flat=True)
        order_items = OrderItem.objects.filter(
            product_id__in=trader_product_ids,
            order__status__in=['pending', 'processing', 'shipped', 'delivered'],
        ).select_related('order', 'product')

        # Auto-create TraderOrderItem records for any that don't exist yet
        existing_ids = set(TraderOrderItem.objects.filter(trader=trader).values_list('order_item_id', flat=True))
        new_records = [
            TraderOrderItem(trader=trader, order_item=oi)
            for oi in order_items if oi.id not in existing_ids
        ]
        if new_records:
            TraderOrderItem.objects.bulk_create(new_records, ignore_conflicts=True)

        qs = TraderOrderItem.objects.filter(trader=trader).select_related(
            'order_item__order', 'order_item__product'
        ).order_by('-order_item__order__created_at')

        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        return Response(TraderOrderItemSerializer(qs, many=True).data)


class TraderOrderItemUpdateView(APIView):
    """
    PATCH /api/traders/<uuid>/orders/<id>/
    Trader updates their preparation status: pending → preparing → ready
    """
    permission_classes = (permissions.IsAuthenticated,)

    def patch(self, request, trader_uuid, pk):
        trader = _get_trader_by_uuid(trader_uuid)
        if not trader:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if trader.email != request.user.email and not request.user.is_staff:
            return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            item = TraderOrderItem.objects.select_related(
                'order_item__order', 'order_item__product'
            ).get(pk=pk, trader=trader)
        except TraderOrderItem.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        if new_status not in ('pending', 'preparing', 'ready'):
            return Response({'detail': 'Invalid status.'}, status=status.HTTP_400_BAD_REQUEST)

        item.status = new_status
        item.note = request.data.get('note', item.note)
        item.status_changed_by = request.user
        if new_status == 'ready' and item.ready_at is None:
            item.ready_at = timezone.now()
        item.save(update_fields=['status', 'note', 'status_changed_by', 'ready_at', 'updated_at'])
        return Response(TraderOrderItemSerializer(item).data)
