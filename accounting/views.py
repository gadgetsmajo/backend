from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from datetime import date, timedelta
from orders.models import Order, Payment
from products.models import Product
from .models import (
    Supplier, Purchase, ExpenseCategory, Expense, Account, AccountTransfer,
    Receivable, Payable, TaxRecord, Refund, Employee, FixedAsset, AuditLog
)
from .serializers import (
    SupplierSerializer, PurchaseSerializer, ExpenseCategorySerializer, ExpenseSerializer,
    AccountSerializer, AccountTransferSerializer, ReceivableSerializer, PayableSerializer,
    TaxRecordSerializer, RefundSerializer, EmployeeSerializer, FixedAssetSerializer, AuditLogSerializer
)


def _log(user, action, model_name, obj_id, old=None, new=None, reason=''):
    try:
        AuditLog.objects.create(user=user, action=action, model_name=model_name,
                                object_id=str(obj_id), old_value=old, new_value=new, reason=reason)
    except Exception:
        pass


# ── Dashboard ────────────────────────────────────────────────────────────────

class AccountingDashboardView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        today = date.today()
        month_start = today.replace(day=1)

        # Revenue — delivered orders total (source of truth for a COD business)
        delivered_orders = Order.objects.filter(status='delivered')
        total_revenue = delivered_orders.aggregate(t=Sum('total'))['t'] or 0
        today_revenue = delivered_orders.filter(created_at__date=today).aggregate(t=Sum('total'))['t'] or 0

        # COGS from purchases
        purchases = Purchase.objects.all()
        cogs = sum(p.landed_cost for p in purchases)

        # Expenses
        total_expenses = Expense.objects.aggregate(t=Sum('amount'))['t'] or 0
        today_expenses = Expense.objects.filter(date=today).aggregate(t=Sum('amount'))['t'] or 0

        # Accounts
        accounts = list(Account.objects.values('name', 'type', 'balance', 'currency'))
        cash_bank = Account.objects.aggregate(t=Sum('balance'))['t'] or 0

        # Inventory value
        products = Product.objects.all()
        from decimal import Decimal
        inventory_cost = sum(
            float(p.purchases.order_by('-purchase_date').first().unit_cost if p.purchases.exists() else p.price * Decimal('0.6')) * p.stock
            for p in products
        )
        inventory_sales_value = sum(p.price * p.stock for p in products)

        # Receivables / Payables
        receivables = Receivable.objects.exclude(status='paid').aggregate(t=Sum('amount'))['t'] or 0
        payables = Payable.objects.exclude(status='paid').aggregate(t=Sum('amount'))['t'] or 0

        # Orders
        today_orders = Order.objects.filter(created_at__date=today).count()
        completed_refunds = Refund.objects.filter(status='completed')
        total_refunds = completed_refunds.aggregate(t=Sum('refund_amount'))['t'] or 0
        today_refunds = completed_refunds.filter(created_at__date=today).aggregate(t=Sum('refund_amount'))['t'] or 0

        gross_profit = float(total_revenue) - float(cogs)
        net_profit = gross_profit - float(total_expenses) - float(total_refunds)
        gross_margin = (gross_profit / float(total_revenue) * 100) if total_revenue else 0
        net_margin = (net_profit / float(total_revenue) * 100) if total_revenue else 0

        # Monthly revenue (last 6 months)
        monthly = (
            Order.objects.filter(status='delivered')
            .annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(revenue=Sum('total'), count=Count('id'))
            .order_by('month')
        )

        return Response({
            'total_revenue': float(total_revenue),
            'cogs': float(cogs),
            'gross_profit': gross_profit,
            'total_expenses': float(total_expenses),
            'net_profit': net_profit,
            'gross_margin': round(gross_margin, 2),
            'net_margin': round(net_margin, 2),
            'cash_bank': float(cash_bank),
            'inventory_cost': float(inventory_cost),
            'inventory_sales_value': float(inventory_sales_value),
            'receivables': float(receivables),
            'payables': float(payables),
            'today_revenue': float(today_revenue),
            'today_expenses': float(today_expenses),
            'today_orders': today_orders,
            'today_refunds': float(today_refunds),
            'total_refunds': float(total_refunds),
            'accounts': accounts,
            'monthly': [{'month': m['month'].strftime('%b %Y'), 'revenue': float(m['revenue']), 'count': m['count']} for m in monthly],
        })


# ── Suppliers ────────────────────────────────────────────────────────────────

class SupplierListCreateView(generics.ListCreateAPIView):
    queryset = Supplier.objects.all().order_by('-created_at')
    serializer_class = SupplierSerializer
    permission_classes = (permissions.IsAdminUser,)

    def perform_create(self, serializer):
        obj = serializer.save()
        _log(self.request.user, 'created', 'Supplier', obj.id, new=serializer.data)


class SupplierDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Purchases ────────────────────────────────────────────────────────────────

class PurchaseListCreateView(generics.ListCreateAPIView):
    queryset = Purchase.objects.select_related('supplier', 'product').order_by('-purchase_date')
    serializer_class = PurchaseSerializer
    permission_classes = (permissions.IsAdminUser,)

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        _log(self.request.user, 'created', 'Purchase', obj.id, new=serializer.data)


class PurchaseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Purchase.objects.select_related('supplier', 'product')
    serializer_class = PurchaseSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Expenses ─────────────────────────────────────────────────────────────────

class ExpenseCategoryListCreateView(generics.ListCreateAPIView):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = (permissions.IsAdminUser,)


class ExpenseListCreateView(generics.ListCreateAPIView):
    serializer_class = ExpenseSerializer
    permission_classes = (permissions.IsAdminUser,)

    def get_queryset(self):
        qs = Expense.objects.select_related('category', 'approved_by').order_by('-date')
        group = self.request.query_params.get('group')
        if group:
            qs = qs.filter(category__group=group)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        _log(self.request.user, 'created', 'Expense', obj.id, new=serializer.data)


class ExpenseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Expense.objects.select_related('category', 'approved_by')
    serializer_class = ExpenseSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Accounts ─────────────────────────────────────────────────────────────────

class AccountListCreateView(generics.ListCreateAPIView):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = (permissions.IsAdminUser,)


class AccountDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = (permissions.IsAdminUser,)


class AccountTransferListCreateView(generics.ListCreateAPIView):
    queryset = AccountTransfer.objects.select_related('from_account', 'to_account').order_by('-date')
    serializer_class = AccountTransferSerializer
    permission_classes = (permissions.IsAdminUser,)

    def perform_create(self, serializer):
        transfer = serializer.save(created_by=self.request.user)
        # Update balances
        transfer.from_account.balance -= transfer.amount
        transfer.from_account.save(update_fields=['balance'])
        transfer.to_account.balance += transfer.amount
        transfer.to_account.save(update_fields=['balance'])
        _log(self.request.user, 'transfer', 'AccountTransfer', transfer.id, new=serializer.data)


# ── Receivables ──────────────────────────────────────────────────────────────

class ReceivableListCreateView(generics.ListCreateAPIView):
    queryset = Receivable.objects.order_by('due_date')
    serializer_class = ReceivableSerializer
    permission_classes = (permissions.IsAdminUser,)


class ReceivableDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Receivable.objects.all()
    serializer_class = ReceivableSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Payables ─────────────────────────────────────────────────────────────────

class PayableListCreateView(generics.ListCreateAPIView):
    queryset = Payable.objects.select_related('supplier').order_by('due_date')
    serializer_class = PayableSerializer
    permission_classes = (permissions.IsAdminUser,)


class PayableDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Payable.objects.select_related('supplier')
    serializer_class = PayableSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Tax ──────────────────────────────────────────────────────────────────────

class TaxRecordListCreateView(generics.ListCreateAPIView):
    queryset = TaxRecord.objects.order_by('-period_end')
    serializer_class = TaxRecordSerializer
    permission_classes = (permissions.IsAdminUser,)


class TaxRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = TaxRecord.objects.all()
    serializer_class = TaxRecordSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Refunds ──────────────────────────────────────────────────────────────────

class RefundListCreateView(generics.ListCreateAPIView):
    queryset = Refund.objects.select_related('order').order_by('-created_at')
    serializer_class = RefundSerializer
    permission_classes = (permissions.IsAdminUser,)

    def perform_create(self, serializer):
        obj = serializer.save()
        _log(self.request.user, 'created', 'Refund', obj.id, new=serializer.data)


class RefundDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Refund.objects.select_related('order')
    serializer_class = RefundSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Employees ────────────────────────────────────────────────────────────────

class EmployeeListCreateView(generics.ListCreateAPIView):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = (permissions.IsAdminUser,)


class EmployeeDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Fixed Assets ─────────────────────────────────────────────────────────────

class FixedAssetListCreateView(generics.ListCreateAPIView):
    queryset = FixedAsset.objects.order_by('-purchase_date')
    serializer_class = FixedAssetSerializer
    permission_classes = (permissions.IsAdminUser,)


class FixedAssetDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FixedAsset.objects.all()
    serializer_class = FixedAssetSerializer
    permission_classes = (permissions.IsAdminUser,)


# ── Audit Log ────────────────────────────────────────────────────────────────

class AuditLogListView(generics.ListAPIView):
    queryset = AuditLog.objects.select_related('user').order_by('-created_at')
    serializer_class = AuditLogSerializer
    permission_classes = (permissions.IsAdminUser,)
