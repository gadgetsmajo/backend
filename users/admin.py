from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import EmailDelivery, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'name', 'is_staff', 'created_at')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal', {'fields': ('name', 'phone', 'avatar')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
    )
    add_fieldsets = (
        (None, {'fields': ('email', 'name', 'password1', 'password2')}),
    )
    search_fields = ('email', 'name')


@admin.register(EmailDelivery)
class EmailDeliveryAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'department', 'sender', 'recipient', 'subject', 'status', 'provider_message_id')
    list_filter = ('department', 'status')
    search_fields = ('recipient', 'subject', 'provider_message_id')
    readonly_fields = (
        'idempotency_key',
        'department',
        'sender',
        'recipient',
        'subject',
        'provider_message_id',
        'status',
        'error_type',
        'sent_at',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
