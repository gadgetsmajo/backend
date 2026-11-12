import logging

from django.core.cache import cache
from django_redis.exceptions import ConnectionInterrupted
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)


def invalidate_category_cache():
    try:
        cache.delete_many(('categories:list:v4:admin', 'categories:list:v4:public'))
    except (ConnectionInterrupted, RedisError):
        logger.exception('Category list cache invalidation failed.')
