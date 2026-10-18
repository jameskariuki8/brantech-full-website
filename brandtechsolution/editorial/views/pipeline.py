import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from staff.decorators import capability_required_api
from editorial.models import EditorialPipelineRun
from editorial.tasks import run_editorial_pipeline_task


@capability_required_api('publish_blog')
def trigger_pipeline_api(request):
    """Queue an autonomous pipeline cycle and return immediately.

    This used to run the whole cycle inline. The cycle makes eight sequential
    Gemini calls and takes around three minutes, so behind the Cloudflare
    tunnel the connection was killed at 100s and the browser was handed a 524
    HTML page where it expected JSON -- while the work carried on to
    completion, invisibly. It now returns 202 with a run id to poll.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        body = json.loads(request.body.decode('utf-8')) if request.body else {}
        limit = int(body.get('limit', 1))
        auto_publish = bool(body.get('auto_publish', False))
    except Exception:
        limit = 1
        auto_publish = False

    limit = max(1, min(limit, 5))

    # One cycle at a time. Two concurrent runs would research and draft the
    # same prioritised topics, doubling the model spend for duplicate output.
    active = EditorialPipelineRun.objects.filter(status__in=['queued', 'running']).first()
    if active:
        return JsonResponse({
            'status': 'already_running',
            'run_id': active.pk,
            'detail': 'A pipeline run is already in progress.',
        }, status=409)

    run = EditorialPipelineRun.objects.create(
        limit=limit,
        auto_publish=auto_publish,
        triggered_by=request.user if request.user.is_authenticated else None,
    )

    # on_commit so the worker cannot pick the task up before the row it needs
    # is committed -- the worker has its own connection and would not see it.
    transaction.on_commit(lambda: run_editorial_pipeline_task.delay(run.pk))

    return JsonResponse(_run_payload(run), status=202)


def _run_payload(run):
    """Serialise a pipeline run for the dashboard poller."""
    return {
        'status': run.status,
        'run_id': run.pk,
        'stage': run.stage,
        'stage_label': run.stage_label,
        'stage_index': run.stage_index,
        'stage_total': len(EditorialPipelineRun.STAGES),
        'error': run.error,
        'articles_processed': run.articles.count() if run.is_terminal else 0,
        'articles': [
            {'id': a.id, 'title': a.title, 'status': a.status}
            for a in run.articles.all()
        ] if run.is_terminal else [],
    }


@capability_required_api('manage_blog')
def pipeline_run_status_api(request, run_id):
    """Poll target for a queued pipeline run."""
    run = get_object_or_404(EditorialPipelineRun, pk=run_id)
    return JsonResponse(_run_payload(run))
