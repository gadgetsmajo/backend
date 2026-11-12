from django.contrib import admin
from django.core.cache import cache
from .cache import invalidate_category_cache
from .models import Category, CategoryAttribute, Product, ProductVariant, ProductReview, ReviewImage


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 0


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'slug', 'position', 'is_active', 'product_count')
    list_editable = ('position', 'is_active')
    list_filter = ('is_active', 'parent')
    search_fields = ('name', 'slug')
    inlines = (CategoryAttributeInline,)
    actions = ('deactivate_categories',)

    @admin.display(description='Products')
    def product_count(self, obj):
        return obj.products.count()

    @admin.action(description='Deactivate selected categories')
    def deactivate_categories(self, request, queryset):
        queryset.update(is_active=False)
        cache.delete_many(('categories:list:v4:admin', 'categories:list:v4:public'))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete_many(('categories:list:v4:admin', 'categories:list:v4:public'))

    def delete_model(self, request, obj):
        obj.is_active = False
        obj.save(update_fields=('is_active',))
        cache.delete_many(('categories:list:v4:admin', 'categories:list:v4:public'))

    def delete_queryset(self, request, queryset):
        queryset.update(is_active=False)
        cache.delete_many(('categories:list:v4:admin', 'categories:list:v4:public'))


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'stock', 'review_status', 'is_active', 'created_at')
    list_filter = ('review_status', 'is_active', 'category')
    search_fields = ('name', 'brand', 'slug')
    inlines = (ProductVariantInline,)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_category_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_category_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_category_cache()


admin.site.register(ProductReview)
admin.site.register(ReviewImage)
