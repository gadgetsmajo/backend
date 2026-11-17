from django.contrib import admin
from django.urls import path, include
from .email_preview import email_preview
from users.webhooks import ResendWebhookView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')),
    path('api/products/', include('products.urls')),
    path('api/orders/', include('orders.urls')),
    path('api/settings/', include('settings_app.urls')),
    path('api/inventory/', include('inventory.urls')),
    path('api/accounting/', include('accounting.urls')),
    path('api/data/', include('orders.data_urls')),
    path('api/advertising/', include('advertising.urls')),
    path('api/traders/', include('traders.urls')),
    path('api/webhooks/resend/', ResendWebhookView.as_view(), name='resend-webhook'),
    path('email-preview/', email_preview),
]
