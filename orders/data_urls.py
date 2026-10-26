from django.urls import path
from .data_views import (
    ExportProductsView, ExportOrdersView, ExportUsersView,
    ImportProductsView, ImportCategoriesView,
    ClearAllOrdersView, ResetInventoryView, ClearOtherDataView,
)

urlpatterns = [
    path('export/products/', ExportProductsView.as_view(), name='export-products'),
    path('export/orders/', ExportOrdersView.as_view(), name='export-orders'),
    path('export/users/', ExportUsersView.as_view(), name='export-users'),
    path('import/products/', ImportProductsView.as_view(), name='import-products'),
    path('import/categories/', ImportCategoriesView.as_view(), name='import-categories'),
    path('danger/clear-orders/', ClearAllOrdersView.as_view(), name='clear-orders'),
    path('danger/reset-inventory/', ResetInventoryView.as_view(), name='reset-inventory'),
    path('danger/clear-other-data/', ClearOtherDataView.as_view(), name='clear-other-data'),
]
