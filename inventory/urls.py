from django.urls import path
from .views import InventorySummaryView, StockMovementListCreateView

urlpatterns = [
    path('summary/', InventorySummaryView.as_view(), name='inventory-summary'),
    path('movements/', StockMovementListCreateView.as_view(), name='stock-movements'),
]
