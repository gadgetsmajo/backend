from django.contrib import admin
from django.core.cache import cache
from .models import Category, Product, ProductReview, ReviewImage


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete('categories:list')

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        cache.delete('categories:list')


admin.site.register(Product)
admin.site.register(ProductReview)
admin.site.register(ReviewImage)
