from rest_framework import serializers
from .models import (
    Supplier, Purchase, ExpenseCategory, Expense, Account, AccountTransfer,
    Receivable, Payable, TaxRecord, Refund, Employee, FixedAsset, AuditLog
)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'


class PurchaseSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    landed_cost = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Purchase
        fields = '__all__'


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = '__all__'


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_group = serializers.CharField(source='category.group', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.name', read_only=True, default=None)

    class Meta:
        model = Expense
        fields = '__all__'


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = '__all__'


class AccountTransferSerializer(serializers.ModelSerializer):
    from_account_name = serializers.CharField(source='from_account.name', read_only=True)
    to_account_name = serializers.CharField(source='to_account.name', read_only=True)

    class Meta:
        model = AccountTransfer
        fields = '__all__'


class ReceivableSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Receivable
        fields = '__all__'


class PayableSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Payable
        fields = '__all__'


class TaxRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRecord
        fields = '__all__'


class RefundSerializer(serializers.ModelSerializer):
    order_code = serializers.CharField(source='order.code', read_only=True, default=None)

    class Meta:
        model = Refund
        fields = '__all__'


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = '__all__'


class FixedAssetSerializer(serializers.ModelSerializer):
    annual_depreciation = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = FixedAsset
        fields = '__all__'


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = '__all__'
