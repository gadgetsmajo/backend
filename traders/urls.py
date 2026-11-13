from django.urls import include, path
from .views import (
    TraderApplicationCreateView,
    TraderMeView, TraderAgreementView, PublicTraderProfileView, TraderProfileView, TraderDashboardView,
    TraderProductListView, TraderProductDetailView,
    TraderSaleListView, TraderExpenseListView,
    TraderInventoryListView, TraderInventoryItemDetailView, TraderStockMovementView,
    TraderOrderListView, TraderOrderItemUpdateView,
    TraderAccountView, TraderWalletView,
    AdminTraderListView, AdminTraderDetailView,
    AdminTraderFinanceView, AdminTraderWithdrawalUpdateView,
    AdminTraderApproveView, AdminTraderRejectView,
    AdminTraderDocumentView,
)

urlpatterns = [
    # Public
    path('apply/',                                                      TraderApplicationCreateView.as_view(), name='trader-apply'),
    path('public/<uuid:trader_uuid>/',                                  PublicTraderProfileView.as_view(),   name='trader-public-profile'),

    # Trader portal (UUID-scoped)
    path('me/',                                                        TraderMeView.as_view(),                name='trader-me'),
    path('<uuid:trader_uuid>/agreement/',                              TraderAgreementView.as_view(),        name='trader-agreement'),
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
    path('<uuid:trader_uuid>/wallet/',                                  TraderWalletView.as_view(),            name='trader-wallet'),
    path('<uuid:trader_uuid>/orders/',                                  TraderOrderListView.as_view(),         name='trader-orders'),
    path('<uuid:trader_uuid>/orders/<int:pk>/',                         TraderOrderItemUpdateView.as_view(),   name='trader-order-item-update'),
    path('<uuid:trader_uuid>/advertising/',                             include('advertising.trader_urls')),

    # Admin
    path('admin/',                                                      AdminTraderListView.as_view(),         name='admin-trader-list'),
    path('admin/finance/',                                              AdminTraderFinanceView.as_view(),      name='admin-trader-finance'),
    path('admin/withdrawals/<int:pk>/',                                 AdminTraderWithdrawalUpdateView.as_view(), name='admin-trader-withdrawal-update'),
    path('admin/<int:pk>/documents/<str:document_type>/',              AdminTraderDocumentView.as_view(),      name='admin-trader-document'),
    path('admin/<int:pk>/',                                             AdminTraderDetailView.as_view(),       name='admin-trader-detail'),
    path('admin/<int:pk>/approve/',                                     AdminTraderApproveView.as_view(),      name='admin-trader-approve'),
    path('admin/<int:pk>/reject/',                                      AdminTraderRejectView.as_view(),       name='admin-trader-reject'),
]
