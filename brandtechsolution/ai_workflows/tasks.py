"""Background work for the harness.

Embedding runs here rather than in the request that triggered it. That is the
pattern editorial/tasks.py already established for article indexing: the call
is a paid network round trip, so inline it slows the save, and a bare
try/except around it means a failure is logged as a warning and the vector
silently never arrives.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name='harness.embed_object',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=4,
)
def embed_object_task(self, app_label, model_name, pk, kind, title, text):
    """Embed one object into the active space.

    Safe to retry: `Memory.remember` upserts on (space, document) and skips
    unchanged text, so a replay costs nothing rather than writing a duplicate
    or paying for the same embedding twice.

    Takes the text as an argument rather than re-reading the row, so the vector
    matches the content that triggered the save even if the row is edited again
    while this is queued.
    """
    from django.apps import apps as django_apps

    from ai_workflows.harness.memory import Memory

    try:
        model = django_apps.get_model(app_label, model_name)
        obj = model.objects.get(pk=pk)
    except Exception:
        # A row deleted between the save and this task is not an error worth
        # retrying four times.
        logger.info("[harness] %s.%s #%s is gone; nothing to embed",
                    app_label, model_name, pk)
        return {'status': 'missing'}

    # `site`, matching the backfill migration: this task indexes BlogPost and
    # Project rows, which is the corpus the assistant answers from. Left in
    # `default` it would sit in a scope nothing reads.
    Memory(scope="site").remember(text, title=title, kind=kind, obj=obj)
    return {'status': 'ok', 'pk': pk}


@shared_task(name='harness.refresh_catalogue')
def refresh_catalogue_task():
    """Verify every provider and rebuild the model catalogue.

    Daily rather than hourly: model lists move in weeks, and a refresh is a
    handful of cheap calls. Not retried -- the next tick does the same work,
    and a retry would only race it.
    """
    from ai_workflows.harness.catalogue import refresh

    result = refresh()
    return {
        'providers': {name: provider.status
                      for name, provider in result['providers'].items()},
        'borrowed': result['borrowed'],
        'manual': result['manual'],
    }
