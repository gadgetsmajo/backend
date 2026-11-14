from django.contrib import admin

from .models import (
    AdvertisingCampaign,
    AdvertisingCampaignOffer,
    AdvertisingClick,
    AdvertisingImpression,
    AdvertisingPayment,
    AdvertisingWallet,
    AdvertisingWalletTransaction,
)
from .notifications import notify_campaign_status


class CampaignOfferInline(admin.TabularInline):
    model = AdvertisingCampaignOffer
    extra = 0
    readonly_fields = ('trader_offer', 'catalog_product', 'created_at')
    can_delete = False


@admin.register(AdvertisingCampaign)
class AdvertisingCampaignAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'trader', 'status', 'max_cpc', 'daily_budget', 'total_budget', 'start_date', 'end_date')
    list_filter = ('status', 'start_date', 'end_date')
    search_fields = ('name', 'trader__business_name', 'trader__email')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at')
    inlines = (CampaignOfferInline,)

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = AdvertisingCampaign.objects.filter(pk=obj.pk).values_list(
                'status', flat=True,
            ).first()
        super().save_model(request, obj, form, change)
        if previous_status is not None and previous_status != obj.status:
            notify_campaign_status(obj)


@admin.register(AdvertisingWallet)
class AdvertisingWalletAdmin(admin.ModelAdmin):
    list_display = ('trader', 'balance', 'currency', 'updated_at')
    search_fields = ('trader__business_name', 'trader__email')
    readonly_fields = ('trader', 'balance', 'currency', 'created_at', 'updated_at')


@admin.register(AdvertisingWalletTransaction)
class AdvertisingWalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('reference', 'wallet', 'transaction_type', 'amount', 'balance_after', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('reference', 'wallet__trader__business_name', 'reason')
    readonly_fields = (
        'wallet', 'transaction_type', 'amount', 'balance_after', 'reference',
        'campaign', 'payment', 'reason', 'created_by', 'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AdvertisingPayment)
class AdvertisingPaymentAdmin(admin.ModelAdmin):
    list_display = ('provider_reference', 'trader', 'provider', 'amount', 'status', 'created_at')
    search_fields = ('provider_reference', 'trader__business_name')
    readonly_fields = ('trader', 'provider', 'provider_reference', 'idempotency_key', 'amount', 'status', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AdvertisingClick)
class AdvertisingClickAdmin(admin.ModelAdmin):
    list_display = ('id', 'campaign_offer', 'status', 'charged_amount', 'reason', 'created_at')
    list_filter = ('status', 'created_at')
    readonly_fields = tuple(field.name for field in AdvertisingClick._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AdvertisingImpression)
class AdvertisingImpressionAdmin(admin.ModelAdmin):
    list_display = ('id', 'campaign_offer', 'impression_date', 'created_at')
    readonly_fields = tuple(field.name for field in AdvertisingImpression._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
