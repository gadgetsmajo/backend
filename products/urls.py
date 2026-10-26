from django.urls import path
from .views import (
    CategoryListView, CategoryDetailView,
    ProductListView, ProductDetailView, ProductSlugDetailView,
    ProductImageDeleteView, ProductStockAddView,
    FlashSaleListCreateView, FlashSaleDetailView,
    ProductShareView,
    ProductReviewListCreateView, ProductReviewDetailView,
    ProductReviewEligibilityView, ProductRatingSummaryView,
    MyReviewsView, RecommendedProductsView,
)

urlpatterns = [
    path('', ProductListView.as_view(), name='product-list'),
    path('recommended/', RecommendedProductsView.as_view(), name='product-recommendations'),
    path('reviews/mine/', MyReviewsView.as_view(), name='my-reviews'),
    path('flash-sales/', FlashSaleListCreateView.as_view(), name='flash-sale-list'),
    path('flash-sales/<int:pk>/', FlashSaleDetailView.as_view(), name='flash-sale-detail'),
    path('<int:pk>/', ProductDetailView.as_view(), name='product-detail'),
    path('<int:pk>/stock/', ProductStockAddView.as_view(), name='product-stock-add'),
    path('<int:pk>/images/<int:img_pk>/', ProductImageDeleteView.as_view(), name='product-image-delete'),
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category-detail'),
    path('share/products/<slug:slug>/', ProductShareView, name='product-share'),
    path('<slug:slug>/reviews/', ProductReviewListCreateView.as_view(), name='product-reviews'),
    path('<slug:slug>/reviews/summary/', ProductRatingSummaryView.as_view(), name='product-reviews-summary'),
    path('<slug:slug>/reviews/eligibility/', ProductReviewEligibilityView.as_view(), name='product-reviews-eligibility'),
    path('<slug:slug>/reviews/<int:pk>/', ProductReviewDetailView.as_view(), name='product-review-detail'),
    path('<slug:slug>/', ProductSlugDetailView.as_view(), name='product-detail-by-slug'),
]
