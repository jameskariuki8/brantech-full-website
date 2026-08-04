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
    """Refresh GitHub repository metadata for synced projects.

    Previously only ever run by hand. On Beat it keeps project cards current
    without anyone remembering to run it. Safe to retry -- the command reads
    from the GitHub API and overwrites project fields, so a repeat is a no-op
    beyond the API calls, which is exactly what you want when the failure was
    a rate limit.
    """
    call_command('sync_github', verbosity=0)
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
