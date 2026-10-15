from django.urls import path
from .views import (
    OrderListCreateView, OrderDetailView, OrderCancelView, ServiceRatingView,
    ReturnRequestView, ReturnRequestListView,
    AdminOrderListView, AdminOrderDetailView, AdminOrderConfirmView, AdminOrderCancelView,
    AdminOrderShipView, AdminOrderReadyForPickupView, AdminOrderDeliverView,
    InitiatePaymentView, PesapalIPNView, AdminPaymentsView,
    AdminReturnRequestListView, AdminReturnRequestApproveView, AdminReturnRequestRejectView,
    AdminReturnRequestRefundedView,
)
from .data_views import (
    ExportProductsView, ExportOrdersView, ExportUsersView,
    ImportProductsView, ImportCategoriesView,
    ClearAllOrdersView, ResetInventoryView,
)

urlpatterns = [
    # ── Data management (must be before <str:code>/ catch-alls) ──────────────
    path('export/products/', ExportProductsView.as_view(), name='export-products'),
    path('export/orders/', ExportOrdersView.as_view(), name='export-orders'),
    path('export/users/', ExportUsersView.as_view(), name='export-users'),
    path('import/products/', ImportProductsView.as_view(), name='import-products'),
    path('import/categories/', ImportCategoriesView.as_view(), name='import-categories'),
    path('danger/clear-orders/', ClearAllOrdersView.as_view(), name='clear-orders'),
    path('danger/reset-inventory/', ResetInventoryView.as_view(), name='reset-inventory'),

    # ── Orders ────────────────────────────────────────────────────────────────
    path('', OrderListCreateView.as_view(), name='order-list'),
    path('returns/', ReturnRequestListView.as_view(), name='return-list'),
    path('admin/', AdminOrderListView.as_view(), name='admin-order-list'),
    path('admin/returns/', AdminReturnRequestListView.as_view(), name='admin-return-list'),
    path('admin/payments/', AdminPaymentsView.as_view(), name='admin-payments'),
    path('admin/returns/<int:pk>/approve/', AdminReturnRequestApproveView.as_view(), name='admin-return-approve'),
    path('admin/returns/<int:pk>/reject/', AdminReturnRequestRejectView.as_view(), name='admin-return-reject'),
    path('admin/returns/<int:pk>/refunded/', AdminReturnRequestRefundedView.as_view(), name='admin-return-refunded'),
    path('admin/<str:code>/', AdminOrderDetailView.as_view(), name='admin-order-detail'),
    path('admin/<str:code>/confirm/', AdminOrderConfirmView.as_view(), name='admin-order-confirm'),
    path('admin/<str:code>/cancel/', AdminOrderCancelView.as_view(), name='admin-order-cancel'),
    path('admin/<str:code>/ship/', AdminOrderShipView.as_view(), name='admin-order-ship'),
    path('admin/<str:code>/ready-for-pickup/', AdminOrderReadyForPickupView.as_view(), name='admin-order-ready-for-pickup'),
    path('admin/<str:code>/deliver/', AdminOrderDeliverView.as_view(), name='admin-order-deliver'),
    path('pesapal/ipn/', PesapalIPNView.as_view(), name='pesapal-ipn'),
    path('<str:code>/', OrderDetailView.as_view(), name='order-detail'),
    path('<str:code>/cancel/', OrderCancelView.as_view(), name='order-cancel'),
    path('<str:code>/pay/', InitiatePaymentView.as_view(), name='order-pay'),
    path('<str:code>/rate/', ServiceRatingView.as_view(), name='order-rate'),
    path('<str:code>/return/', ReturnRequestView.as_view(), name='order-return'),
]
