from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminOrReadOnly(BasePermission):
    """Allow admin users to write, everyone else read-only."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user and request.user.is_staff


class IsAdminOrProductOwnerOrReadOnly(BasePermission):
    """Allow traders to mutate their own products while keeping other writes admin-only."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        if request.method not in ('PUT', 'PATCH', 'DELETE'):
            return False

        trader = getattr(request.user, 'trader_application', None)
        if trader is None:
            return False
        return (
            obj.trader_id == trader.pk
            or (
                obj.trader_product_id is not None
                and obj.trader_product.trader_id == trader.pk
            )
        )
