from django.contrib import admin
from django.core.cache import cache
from .models import Category, CategoryAttribute, Product, ProductVariant, ProductReview, ReviewImage


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 0


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'slug')
    search_fields = ('name', 'slug')
    inlines = (CategoryAttributeInline,)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete('categories:list:v3')

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        cache.delete('categories:list:v3')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'stock', 'review_status', 'is_active', 'created_at')
    list_filter = ('review_status', 'is_active', 'category')
    search_fields = ('name', 'brand', 'slug')
    inlines = (ProductVariantInline,)


admin.site.register(ProductReview)
admin.site.register(ReviewImage)
