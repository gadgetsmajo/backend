import logging

from django.core.cache import cache
from django_redis.exceptions import ConnectionInterrupted
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)
product_logger = logging.getLogger('products.views')


def invalidate_category_cache():
    try:
        cache.delete_many(('categories:list:v5:admin', 'categories:list:v5:public'))
    except (ConnectionInterrupted, RedisError):
        logger.exception('Category list cache invalidation failed.')


def invalidate_product_cache(product_id=None):
    try:
        cache.delete('products:list')
        if product_id is not None:
            cache.delete(f'products:detail:{product_id}')
    except (ConnectionInterrupted, RedisError):
        product_logger.exception('Product cache invalidation failed for product %s.', product_id)
