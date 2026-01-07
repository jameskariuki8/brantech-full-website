"""
Performance utilities for caching and optimization.
"""
from functools import wraps
from django.core.cache import cache
from django.conf import settings
import hashlib
import json


def cache_query_result(timeout=300, key_prefix='query'):
    """
    Decorator to cache database query results.
    
    Args:
        timeout: Cache timeout in seconds (default 5 minutes)
        key_prefix: Prefix for cache key
    
    Usage:
        @cache_query_result(timeout=600)
        def get_featured_posts():
            return BlogPost.objects.filter(featured=True)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Skip caching in DEBUG mode unless explicitly enabled
            if getattr(settings, 'DEBUG', False) and not getattr(settings, 'ENABLE_QUERY_CACHE_IN_DEBUG', False):
                return func(*args, **kwargs)
            
            # Generate cache key from function name and arguments
            cache_key_parts = [key_prefix, func.__module__, func.__name__]
            
            # Add args to cache key
            if args:
                args_str = json.dumps(args, sort_keys=True, default=str)
                cache_key_parts.append(hashlib.md5(args_str.encode()).hexdigest()[:8])
            
            # Add kwargs to cache key
            if kwargs:
                kwargs_str = json.dumps(kwargs, sort_keys=True, default=str)
                cache_key_parts.append(hashlib.md5(kwargs_str.encode()).hexdigest()[:8])
            
            cache_key = ':'.join(cache_key_parts)
            
            # Try to get from cache
            result = cache.get(cache_key)
            if result is not None:
                return result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            
            return result
        
        return wrapper
    return decorator


def invalidate_cache_prefix(key_prefix):
    """
    Invalidate all cache entries with a specific prefix.
    
    Args:
        key_prefix: The cache key prefix to invalidate
    
    Note: This is a best-effort approach. For production use with Redis,
    consider using cache versioning or more sophisticated cache invalidation.
    """
    # Django's default cache doesn't support prefix-based deletion
    # This is a placeholder for when Redis or Memcached is used
    # For now, we can only clear all cache
    if hasattr(cache, 'delete_pattern'):
        # Redis backend supports pattern deletion
        cache.delete_pattern(f"{key_prefix}:*")
    # For other backends, manual key tracking would be needed
