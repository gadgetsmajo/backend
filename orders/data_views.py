import csv
import io
import json
from django.db import transaction
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework import permissions, status
from rest_framework.response import Response
from orders.models import Order
from products.models import Product, Category
from django.contrib.auth import get_user_model

User = get_user_model()


def _export(request, filename, fields, rows):
    fmt = request.query_params.get('format', 'csv')
    data = list(rows)
    if fmt == 'json':
        return HttpResponse(
            json.dumps(data, default=str),
            content_type='application/json',
            headers={'Content-Disposition': f'attachment; filename="{filename}.json"'},
        )
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    writer = csv.DictWriter(response, fieldnames=fields)
    writer.writeheader()
    writer.writerows(data)
    return response


class ExportProductsView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        fields = [
            'id', 'name', 'slug', 'category', 'price', 'original_price',
            'delivery_fee', 'stock', 'rating', 'is_active', 'is_featured',
            'trader', 'created_at',
        ]
        rows = Product.objects.select_related('category', 'trader').values(
            'id', 'name', 'slug',
            category='category__name',
            original_price='original_price',
            delivery_fee='delivery_fee',
            stock='stock',
            rating='rating',
            is_active='is_active',
            is_featured='is_featured',
            trader='trader__business_name',
            price='price',
            created_at='created_at',
        )
        return _export(request, 'products', fields, rows)


class ExportOrdersView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        fields = [
            'code', 'user_name', 'user_email', 'status',
            'subtotal', 'delivery_fee', 'total',
            'delivery_address', 'phone', 'note', 'cancel_reason',
            'items_count', 'created_at',
        ]
        orders = (
            Order.objects
            .select_related('user')
            .prefetch_related('items')
            .all()
        )
        rows = []
        for o in orders:
            rows.append({
                'code': o.code,
                'user_name': o.user.name,
                'user_email': o.user.email,
                'status': o.status,
                'subtotal': str(o.subtotal),
                'delivery_fee': str(o.delivery_fee),
                'total': str(o.total),
                'delivery_address': o.delivery_address,
                'phone': o.phone,
                'note': o.note,
                'cancel_reason': o.cancel_reason,
                'items_count': o.items.count(),
                'created_at': str(o.created_at),
            })
        return _export(request, 'orders', fields, rows)


class ExportUsersView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        fields = ['id', 'name', 'email', 'phone', 'region', 'district', 'is_staff', 'is_active', 'created_at']
        rows = User.objects.values('id', 'name', 'email', 'phone', 'region', 'district', 'is_staff', 'is_active', 'created_at')
        return _export(request, 'users', fields, rows)


class ImportProductsView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({'detail': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            text = file.read().decode('utf-8')
        except Exception:
            return Response({'detail': 'Could not decode file. Ensure it is UTF-8 encoded.'}, status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(io.StringIO(text))
        required = {'name', 'price'}
        if not required.issubset(set(reader.fieldnames or [])):
            return Response(
                {'detail': f'CSV must contain columns: {", ".join(required)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created, errors = 0, []
        category_cache = {}

        for i, row in enumerate(reader, start=2):
            name = row.get('name', '').strip()
            if not name:
                errors.append(f'Row {i}: missing name.')
                continue
            try:
                price = float(row.get('price', 0))
            except ValueError:
                errors.append(f'Row {i}: invalid price "{row.get("price")}".')
                continue

            cat_name = row.get('category', '').strip()
            category = None
            if cat_name:
                if cat_name not in category_cache:
                    from django.utils.text import slugify
                    category_cache[cat_name], _ = Category.objects.get_or_create(
                        name=cat_name,
                        defaults={'slug': slugify(cat_name)},
                    )
                category = category_cache[cat_name]

            def _bool(val):
                return str(val).strip().lower() in ('1', 'true', 'yes')

            def _decimal_or_none(val):
                try:
                    return float(val) if val and str(val).strip() else None
                except ValueError:
                    return None

            Product.objects.create(
                name=name,
                price=price,
                category=category,
                original_price=_decimal_or_none(row.get('original_price')),
                stock=int(row.get('stock') or 0),
                delivery_fee=float(row.get('delivery_fee') or 0),
                short_description=row.get('short_description', '').strip()[:300],
                is_active=_bool(row.get('is_active', '1')),
                is_featured=_bool(row.get('is_featured', '0')),
            )
            created += 1

        return Response({'created': created, 'errors': errors})


class ImportCategoriesView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({'detail': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            text = file.read().decode('utf-8')
        except Exception:
            return Response({'detail': 'Could not decode file.'}, status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(io.StringIO(text))
        if 'name' not in (reader.fieldnames or []):
            return Response({'detail': 'CSV must contain a "name" column.'}, status=status.HTTP_400_BAD_REQUEST)

        created, skipped, errors = 0, 0, []

        for i, row in enumerate(reader, start=2):
            from django.utils.text import slugify
            name = row.get('name', '').strip()
            if not name:
                errors.append(f'Row {i}: missing name.')
                continue
            _, was_created = Category.objects.get_or_create(
                name=name,
                defaults={'slug': slugify(name)},
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        return Response({'created': created, 'skipped': skipped, 'errors': errors})


class ClearAllOrdersView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        password = request.data.get('password', '')
        if not request.user.check_password(password):
            return Response({'detail': 'Incorrect password.'}, status=status.HTTP_403_FORBIDDEN)
        count, _ = Order.objects.all().delete()
        return Response({'deleted': count})


class ResetInventoryView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        password = request.data.get('password', '')
        if not request.user.check_password(password):
            return Response({'detail': 'Incorrect password.'}, status=status.HTTP_403_FORBIDDEN)
        from inventory.models import StockMovement
        movements_deleted, _ = StockMovement.objects.all().delete()
        products_reset = Product.objects.update(stock=0)
        return Response({'products_reset': products_reset, 'movements_deleted': movements_deleted})


class ClearOtherDataView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        password = request.data.get('password', '')
        if not request.user.check_password(password):
            return Response({'detail': 'Incorrect password.'}, status=status.HTTP_403_FORBIDDEN)

        from accounting.models import (
            Account, AccountTransfer, AuditLog, Employee, Expense, ExpenseCategory,
            FixedAsset, Payable, Purchase, Receivable, Refund, Supplier, TaxRecord,
        )
        from traders.models import TraderExpense, TraderOrderItem, TraderSale
        from users.models import CartItem, Notification, UserBehaviour, WishlistItem
        from products.models import FlashSale, ProductReview, ReviewImage

        delete_sets = [
            ('payments', Payment),
            ('orders', Order),
            ('service_ratings', ServiceRating),
            ('return_requests', ReturnRequest),
            ('order_items', OrderItem),
            ('flash_sales', FlashSale),
            ('product_reviews', ProductReview),
            ('review_images', ReviewImage),
            ('suppliers', Supplier),
            ('purchases', Purchase),
            ('expense_categories', ExpenseCategory),
            ('expenses', Expense),
            ('accounts', Account),
            ('account_transfers', AccountTransfer),
            ('receivables', Receivable),
            ('payables', Payable),
            ('tax_records', TaxRecord),
            ('refunds', Refund),
            ('employees', Employee),
            ('fixed_assets', FixedAsset),
            ('audit_logs', AuditLog),
            ('trader_sales', TraderSale),
            ('trader_expenses', TraderExpense),
            ('trader_order_items', TraderOrderItem),
            ('notifications', Notification),
            ('cart_items', CartItem),
            ('wishlist_items', WishlistItem),
            ('user_behaviour', UserBehaviour),
        ]

        deleted = {}
        with transaction.atomic():
            for label, model in delete_sets:
                deleted[label] = model.objects.count()
                model.objects.all().delete()

        return Response({'deleted': deleted, 'total_deleted': sum(deleted.values())})
