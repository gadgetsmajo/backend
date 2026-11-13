from django.urls import path

from .views import (
    TraderAdvertisingCampaignDetailView,
    TraderAdvertisingCampaignsView,
    TraderAdvertisingOffersView,
    TraderAdvertisingRechargeView,
    TraderAdvertisingView,
)

urlpatterns = [
    path('', TraderAdvertisingView.as_view(), name='trader-advertising'),
    path('offers/', TraderAdvertisingOffersView.as_view(), name='trader-advertising-offers'),
    path('wallet/recharge/', TraderAdvertisingRechargeView.as_view(), name='trader-advertising-recharge'),
    path('campaigns/', TraderAdvertisingCampaignsView.as_view(), name='trader-advertising-campaigns'),
    path('campaigns/<int:pk>/', TraderAdvertisingCampaignDetailView.as_view(), name='trader-advertising-campaign-detail'),
]
