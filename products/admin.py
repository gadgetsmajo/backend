from django.contrib import admin
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Sum
from django.forms.models import BaseInlineFormSet
from django.utils import timezone
from .cache import invalidate_category_cache
from .models import Category, CategoryAttribute, Product, ProductVariant, ProductReview, ReviewImage
from traders.models import TraderInventoryItem


class ProductVariantInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.deleted_forms:
            variant = form.instance
            if variant.pk and (
                variant.order_items.exists()
                or variant.trader_inventory_items.exists()
            ):
                raise ValidationError(
                    'Variants with order or inventory history cannot be removed. Mark them unavailable instead.'
                )


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 0


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    formset = ProductVariantInlineFormSet
    readonly_fields = ('sold_quantity',)
    extra = 0

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            sold_quantity=Sum('order_items__quantity'),
        )

    @admin.display(description='Units sold')
    def sold_quantity(self, obj):
        return obj.sold_quantity or 0


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

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model is ProductVariant:
            variants = list(formset.instance.variants.all())
            if variants:
                formset.instance.price = min(variant.price for variant in variants)
                formset.instance.stock = sum(variant.stock for variant in variants)
                formset.instance.save(update_fields=('price', 'stock'))
                for variant in variants:
                    TraderInventoryItem.objects.filter(variant_id=variant.pk).update(
                        quantity=variant.stock,
                        updated_at=timezone.now(),
                    )
                try:
                    trader_product = formset.instance.trader_product
                except ObjectDoesNotExist:
                    trader_product = None
                if trader_product:
                    trader_product.price = formset.instance.price
                    trader_product.stock = formset.instance.stock
                    trader_product.save(update_fields=('price', 'stock', 'updated_at'))
            invalidate_category_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_category_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_category_cache()


admin.site.register(ProductReview)
admin.site.register(ReviewImage)
