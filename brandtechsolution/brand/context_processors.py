from django.core.cache import cache

from .models import SITE_CONTENT_CACHE_KEY, SiteContent


def site_content(request):
    return {
        "site_content": cache.get_or_set(
            SITE_CONTENT_CACHE_KEY,
            lambda: SiteContent.objects.filter(pk=1).first() or SiteContent(),
            timeout=60,
        ),
    }
