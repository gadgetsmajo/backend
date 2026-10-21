from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


class UserAdminBase(BaseUserAdmin):
    ordering = ('-created_at',)
    list_display = ('email', 'phone_number', 'full_name', 'farm_name', 'country', 'admin_level', 'is_active', 'created_at')
    list_filter = ('is_active', 'admin_level', 'country')
    search_fields = ('email', 'phone_number', 'full_name', 'farm_name')
    readonly_fields = ('created_at', 'last_seen', 'profile_updated_at')
    fieldsets = (
        (None, {'fields': ('email', 'phone_number', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'farm_name', 'country', 'avatar_url')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'admin_level',
                                    'can_manage_users', 'can_manage_devices',
                                    'can_manage_weather', 'can_manage_system',
                                    'weather_access', 'must_change_password')}),
        ('Timestamps', {'fields': ('created_at', 'last_seen', 'profile_updated_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'phone_number', 'full_name', 'password1', 'password2'),
        }),
    )
    filter_horizontal = ()


# ── Proxy models so Django admin shows two separate sections ──────────────────

class RegularUser(User):
    class Meta:
        proxy = True
        verbose_name = 'User'
        verbose_name_plural = 'Users'


class AdminUser(User):
    class Meta:
        proxy = True
        verbose_name = 'Admin'
        verbose_name_plural = 'Admins'


@admin.register(RegularUser)
class RegularUserAdmin(UserAdminBase):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(admin_level='user')

    def save_model(self, request, obj, form, change):
        obj.admin_level = 'user'
        super().save_model(request, obj, form, change)


@admin.register(AdminUser)
class AdminUserAdmin(UserAdminBase):
    def get_queryset(self, request):
        return super().get_queryset(request).exclude(admin_level='user')
