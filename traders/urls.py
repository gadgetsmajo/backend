from django.urls import path
from .views import (
    TraderApplicationCreateView,
    TraderMeView, PublicTraderProfileView, TraderProfileView, TraderDashboardView,
    TraderProductListView, TraderProductDetailView,
    TraderSaleListView, TraderExpenseListView,
    TraderInventoryListView, TraderInventoryItemDetailView, TraderStockMovementView,
    TraderOrderListView, TraderOrderItemUpdateView,
    TraderAccountView,
    AdminTraderListView, AdminTraderDetailView,
    AdminTraderApproveView, AdminTraderRejectView,
)

urlpatterns = [
    # Public
    path('apply/',                                                      TraderApplicationCreateView.as_view(), name='trader-apply'),
    path('public/<uuid:trader_uuid>/',                                  PublicTraderProfileView.as_view(),   name='trader-public-profile'),

    # Trader portal (UUID-scoped)
    path('me/',                                                        TraderMeView.as_view(),                name='trader-me'),
    path('<uuid:trader_uuid>/profile/',                                 TraderProfileView.as_view(),           name='trader-profile'),
    path('<uuid:trader_uuid>/dashboard/',                               TraderDashboardView.as_view(),         name='trader-dashboard'),
    path('<uuid:trader_uuid>/products/',                                TraderProductListView.as_view(),       name='trader-products'),
    path('<uuid:trader_uuid>/products/<uuid:product_uuid>/',            TraderProductDetailView.as_view(),     name='trader-product-detail'),
    path('<uuid:trader_uuid>/sales/',                                   TraderSaleListView.as_view(),          name='trader-sales'),
    path('<uuid:trader_uuid>/expenses/',                                TraderExpenseListView.as_view(),       name='trader-expenses'),
    path('<uuid:trader_uuid>/inventory/',                               TraderInventoryListView.as_view(),     name='trader-inventory'),
    path('<uuid:trader_uuid>/inventory/<int:pk>/',                      TraderInventoryItemDetailView.as_view(), name='trader-inventory-item'),
    path('<uuid:trader_uuid>/inventory/<int:pk>/movements/',            TraderStockMovementView.as_view(),     name='trader-stock-movement'),
    path('<uuid:trader_uuid>/account/',                                 TraderAccountView.as_view(),           name='trader-account'),
    path('<uuid:trader_uuid>/orders/',                                  TraderOrderListView.as_view(),         name='trader-orders'),
    path('<uuid:trader_uuid>/orders/<int:pk>/',                         TraderOrderItemUpdateView.as_view(),   name='trader-order-item-update'),

    # Admin
    path('admin/',                                                      AdminTraderListView.as_view(),         name='admin-trader-list'),
    path('admin/<int:pk>/',                                             AdminTraderDetailView.as_view(),       name='admin-trader-detail'),
    path('admin/<int:pk>/approve/',                                     AdminTraderApproveView.as_view(),      name='admin-trader-approve'),
    path('admin/<int:pk>/reject/',                                      AdminTraderRejectView.as_view(),       name='admin-trader-reject'),
]
