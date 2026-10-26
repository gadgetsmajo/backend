from django.urls import path
from .accounting_views import AccountingSummaryView, AccountingTransactionsView

urlpatterns = [
    path('summary/', AccountingSummaryView.as_view(), name='accounting-summary'),
    path('transactions/', AccountingTransactionsView.as_view(), name='accounting-transactions'),
]
