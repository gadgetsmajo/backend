from celery import shared_task
import logging

logger = logging.getLogger(__name__)


def _product_image(product) -> str:
    try:
        return product.image.url if product.image else ''
    except Exception:
        return ''


@shared_task
def send_product_rating_notifications(order_id: int):
    from orders.models import Order
    from users.models import Notification
    from users.emails import send_product_rating_email

    try:
        order = Order.objects.select_related('user').prefetch_related('items__product').get(id=order_id)
    except Order.DoesNotExist:
        return

    if order.status != 'delivered':
        return

    user = order.user

    # ── Product rating ────────────────────────────────────────────────────────
    product_items = []
    for item in order.items.all():
        if not (item.product and item.product.slug):
            continue
        Notification.objects.create(
            user=user,
            type='product_rating',
            title=f'Review {item.product.name}',
            body=f'You received {item.product.name}. How would you rate it?|{item.product.slug}?order_code={order.code}',
        )
        product_items.append({
            'name': item.product.name,
            'image': _product_image(item.product),
            'slug': item.product.slug,
        })

    if product_items:
        try:
            send_product_rating_email(user.name, user.email, order.code, product_items)
        except Exception:
            logger.exception('Failed to send product rating email for order %s', order.code)
