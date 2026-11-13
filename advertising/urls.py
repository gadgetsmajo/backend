from django.urls import path

from .views import (
    AdminAdvertisingCampaignDetailView,
    AdminAdvertisingCampaignsView,
    AdminAdvertisingWalletAdjustmentsView,
    AdminAdvertisingTransactionsView,
    AdvertisingClicksView,
    AdvertisingImpressionsView,
    SponsoredPlacementsView,
)

urlpatterns = [
    path('placements/', SponsoredPlacementsView.as_view(), name='advertising-placements'),
    path('impressions/', AdvertisingImpressionsView.as_view(), name='advertising-impressions'),
    path('clicks/', AdvertisingClicksView.as_view(), name='advertising-clicks'),
    path('admin/campaigns/', AdminAdvertisingCampaignsView.as_view(), name='advertising-admin-campaigns'),
    path('admin/campaigns/<int:pk>/', AdminAdvertisingCampaignDetailView.as_view(), name='advertising-admin-campaign-detail'),
    path('admin/wallet-adjustments/', AdminAdvertisingWalletAdjustmentsView.as_view(), name='advertising-admin-wallet-adjustments'),
    path('admin/transactions/', AdminAdvertisingTransactionsView.as_view(), name='advertising-admin-transactions'),
]
