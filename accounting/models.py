from django.db import models
from django.conf import settings
from products.models import Product


class Supplier(models.Model):
    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    country = models.CharField(max_length=100, default='Uganda')
    address = models.TextField(blank=True)
    payment_terms = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Purchase(models.Model):
    STATUS = [('pending','Pending'),('partial','Partial'),('paid','Paid')]
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, related_name='purchases')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, related_name='purchases')
    purchase_date = models.DateField()
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customs_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS, default='pending')
    invoice_ref = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def landed_cost(self):
        return (self.unit_cost * self.quantity) + self.shipping_cost + self.customs_cost + self.other_cost

    @property
    def outstanding(self):
        return self.landed_cost - self.amount_paid

    def __str__(self):
        return f'Purchase {self.id} — {self.product}'


class ExpenseCategory(models.Model):
    GROUP_CHOICES = [('operations','Operations'),('technology','Technology'),('marketing','Marketing'),('business','Business'),('other','Other')]
    name = models.CharField(max_length=100)
    group = models.CharField(max_length=20, choices=GROUP_CHOICES, default='other')

    def __str__(self):
        return f'{self.group} / {self.name}'


class Expense(models.Model):
    PAYMENT_METHODS = [('mobile_money','Mobile Money'),('card','Card'),('cash','Cash'),('bank','Bank Transfer'),('other','Other')]
    date = models.DateField()
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='cash')
    vendor = models.CharField(max_length=150, blank=True)
    receipt_url = models.URLField(blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.date} — {self.description} UGX {self.amount}'


class Account(models.Model):
    TYPES = [('bank','Bank'),('mobile_money','Mobile Money'),('cash','Cash'),('gateway','Payment Gateway'),('other','Other')]
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=TYPES)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='UGX')
    notes = models.TextField(blank=True)

    def __str__(self):
        return f'{self.name} ({self.type})'


class AccountTransfer(models.Model):
    from_account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='transfers_out')
    to_account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='transfers_in')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.from_account} → {self.to_account}: {self.amount}'


class Receivable(models.Model):
    STATUS = [('open','Open'),('partial','Partial'),('paid','Paid'),('overdue','Overdue')]
    customer_name = models.CharField(max_length=150)
    customer_email = models.EmailField(blank=True)
    invoice_ref = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS, default='open')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def balance(self):
        return self.amount - self.amount_paid

    def __str__(self):
        return f'Receivable {self.invoice_ref} — {self.customer_name}'


class Payable(models.Model):
    STATUS = [('open','Open'),('partial','Partial'),('paid','Paid'),('overdue','Overdue')]
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, related_name='payables')
    invoice_ref = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS, default='open')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def balance(self):
        return self.amount - self.amount_paid

    def __str__(self):
        return f'Payable {self.invoice_ref} — {self.supplier}'


class TaxRecord(models.Model):
    TAX_TYPES = [('vat','VAT'),('income_tax','Income Tax'),('withholding','Withholding Tax'),('paye','PAYE'),('other','Other')]
    STATUS = [('pending','Pending'),('filed','Filed'),('paid','Paid')]
    tax_type = models.CharField(max_length=20, choices=TAX_TYPES)
    period_start = models.DateField()
    period_end = models.DateField()
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS, default='pending')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.get_tax_type_display()} {self.period_start}–{self.period_end}'


class Refund(models.Model):
    STATUS = [('pending','Pending'),('approved','Approved'),('rejected','Rejected'),('completed','Completed')]
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, related_name='refunds')
    customer_name = models.CharField(max_length=150)
    product_name = models.CharField(max_length=255, blank=True)
    return_reason = models.TextField()
    product_condition = models.CharField(max_length=100, blank=True)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    refund_method = models.CharField(max_length=50, blank=True)
    restock = models.BooleanField(default=False)
    return_delivery_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Refund {self.id} — {self.customer_name}'


class Employee(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=100, blank=True)
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.name


class FixedAsset(models.Model):
    name = models.CharField(max_length=255)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_date = models.DateField()
    useful_life_years = models.PositiveSmallIntegerField(default=3)
    location = models.CharField(max_length=150, blank=True)
    disposal_date = models.DateField(null=True, blank=True)
    disposal_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    @property
    def annual_depreciation(self):
        if self.useful_life_years:
            return self.purchase_price / self.useful_life_years
        return 0

    def __str__(self):
        return self.name


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=50)   # created / updated / deleted / voided
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} {self.action} {self.model_name}#{self.object_id}'
