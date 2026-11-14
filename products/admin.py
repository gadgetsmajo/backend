from django.contrib import admin
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Sum
from django.forms.models import BaseInlineFormSet
from django.template.response import TemplateResponse
from django.utils import timezone
from .cache import invalidate_category_cache, invalidate_product_cache
from .catalog import merge_catalog_products
from .catalog_sync import sync_product_to_catalog
from .models import (
    CatalogProduct, CatalogVariant, Category, CategoryAttribute, Product, ProductVariant, ProductReview,
    ReviewImage,
)
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


class CatalogVariantInline(admin.TabularInline):
    model = CatalogVariant
    fields = ('options', 'image_references', 'is_active', 'position')
    extra = 0

    def has_delete_permission(self, request, obj=None):
        return False


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

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if form.instance.trader_id is None and form.instance.trader_product_id is None:
            sync_product_to_catalog(form.instance)
        invalidate_product_cache(form.instance.pk)

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_category_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_category_cache()


admin.site.register(ProductReview)
admin.site.register(ReviewImage)


@admin.register(CatalogProduct)
class CatalogProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'brand', 'model', 'category', 'review_status', 'is_active', 'created_at')
    list_filter = ('review_status', 'is_active', 'category')
    search_fields = ('name', 'brand', 'model', 'product_type', 'identity_key')
    readonly_fields = ('identity_key', 'created_by', 'created_at', 'updated_at')
    inlines = (CatalogVariantInline,)
    actions = ('approve_catalog_products', 'disable_catalog_products', 'merge_catalog_products_action')

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        product = form.instance
        variants = list(product.variants.filter(is_active=True).values_list('options', flat=True))
        if variants and variants != product.variant_options:
            product.variant_options = variants
            product.save(update_fields=('variant_options', 'updated_at'))

    @admin.action(description='Approve selected catalog products')
    def approve_catalog_products(self, request, queryset):
        for product in queryset:
            for position, options in enumerate(product.variant_options or []):
                if isinstance(options, dict) and options:
                    CatalogVariant.objects.get_or_create(
                        catalog_product=product,
                        options_key=CatalogVariant.make_options_key(options),
                        defaults={'options': options, 'position': position},
                    )
        queryset.update(review_status='approved', is_active=True, review_note='')

    @admin.action(description='Disable selected catalog products')
    def disable_catalog_products(self, request, queryset):
        queryset.update(review_status='disabled', is_active=False)

    @admin.action(description='Merge selected catalog products into one')
    def merge_catalog_products_action(self, request, queryset):
        selected_ids = request.POST.getlist('_selected_action')
        survivor_id = request.POST.get('survivor_id')
        if request.POST.get('confirm_merge'):
            if not survivor_id:
                self.message_user(request, 'Choose the catalog product to keep.', level='error')
                return None
            try:
                survivor, merged_count = merge_catalog_products(
                    [int(value) for value in selected_ids],
                    int(survivor_id),
                )
            except (TypeError, ValueError, CatalogProduct.DoesNotExist) as exc:
                self.message_user(request, str(exc), level='error')
                return None
            self.message_user(
                request,
                f'Merged {merged_count} catalog product(s) into “{survivor.name}”. '
                'Existing listings and order records were preserved.',
            )
            return None

        selected_products = list(queryset.order_by('pk'))
        if len(selected_products) < 2:
            self.message_user(request, 'Select at least two catalog products to merge.', level='error')
            return None
        return TemplateResponse(
            request,
            'admin/products/catalogproduct/merge.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'products': selected_products,
                'action_name': 'merge_catalog_products_action',
                'title': 'Merge catalog products',
            },
        )
