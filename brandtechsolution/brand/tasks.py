"""Celery tasks for the brand app."""
import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(
    name='brand.sync_github',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
    retry_jitter=True,
    max_retries=3,
)
def sync_github_task():
    """Queue due catalogue/account refreshes; their leases coalesce duplicate ticks.

    Catalogue refresh also updates tracked projects, reusing unchanged content.
    Last-good snapshots survive failures and account-wide rate-limit backoff.
    """
    from .github_cache import request_refresh
    request_refresh('catalogue')
    request_refresh('account')
    return {'status': 'ok'}


@shared_task(
    name='brand.rebuild_vector_stores',
    soft_time_limit=3000,
    time_limit=3300,
)
def rebuild_vector_stores_task(force: bool = False):
    """Regenerate content embeddings for blog posts and projects.

    Runs long enough on a full corpus to need its own limits, well above the
    pipeline defaults. Not scheduled -- triggered on demand, since a rebuild
    re-embeds everything and costs real API quota.
    """
    call_command('init_vector_stores', force=force, verbosity=0)
    return {'status': 'ok', 'force': force}


@shared_task(name='brand.refresh_github_cache')
def refresh_github_cache_task(scope, kind, repo_id, token):
    from .github_cache import run_refresh
    return run_refresh(scope, kind, repo_id, token)
