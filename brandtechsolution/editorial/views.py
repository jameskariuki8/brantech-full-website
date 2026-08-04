"""The AI newsroom dashboard.

Every view here is gated on a panel capability. They arrived unauthenticated
and CSRF-exempt, which meant anyone on the internet could POST to
/editorial/api/articles/<id>/approve/ and publish to the live site, or to
/editorial/api/run-pipeline/ and spend the project's model quota. The module
already imported staff_member_required without ever applying it, so the intent
was there.

capability_required rather than staff_member_required: this project gates the
panel on named capabilities (see staff/capabilities.py), and
staff_member_required would admit every is_staff account regardless of role.
Reading the newsroom needs manage_blog; anything that decides what reaches the
public site needs publish_blog, which is the capability that already governs
draft -> published for ordinary posts. Approving here IS publishing, so it
must not be reachable with a weaker permission than the blog editor's.
"""
import json
from django.db import transaction
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse, Http404
from staff.decorators import capability_required, capability_required_api
from trends.models import TrendTopic, CompetitorArticle, TrendPrediction
from research.models import ResearchDossier, VerifiedFactReport
from editorial.models import EditorialArticle, EditorialPipelineRun, SocialPackage
from editorial.tasks import run_editorial_pipeline_task
from approval.services.workflow import HumanApprovalWorkflow
from publishing.services.publisher import PublishingAgent
from knowledge_base.services.knowledge_graph import KnowledgeBaseAgent
from knowledge_base.models import KnowledgeDocument


@capability_required('manage_blog')
def dashboard_view(request):
    """Renders the Teklora AI Autonomous Newsroom Dashboard UI."""
    context = {
        'total_trends': TrendTopic.objects.count(),
        'prioritized_trends': TrendTopic.objects.filter(status='prioritized').count(),
        'pending_reviews': EditorialArticle.objects.filter(status='review_pending'),
        'published_articles': EditorialArticle.objects.filter(status='published')[:10],
        'competitor_gaps': CompetitorArticle.objects.filter(content_gap_score__gt=7.0)[:5],
        'predictions': TrendPrediction.objects.all()[:5],
        'recent_trends': TrendTopic.objects.all()[:10],
        'kb_count': KnowledgeDocument.objects.count(),
    }
    return render(request, 'editorial/dashboard.html', context)


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


@capability_required_api('manage_blog')
def article_detail_api(request, article_id):
    """Returns full JSON metadata for an article (including social package & preview)."""
    article = get_object_or_404(EditorialArticle, pk=article_id)
    social_package = getattr(article, 'social_package', None)

    workflow = HumanApprovalWorkflow()
    html_preview = workflow.export_as_html(article)

    data = {
        'id': article.id,
        'title': article.title,
        'subtitle': article.subtitle,
        'executive_summary': article.executive_summary,
        'target_audience': article.get_target_audience_display(),
        'reading_time_minutes': article.reading_time_minutes,
        'reading_difficulty': article.estimated_reading_difficulty,
        'status': article.status,
        'hero_image_prompt': article.hero_image_prompt,
        'image_alt_text': article.image_alt_text,
        'html_preview': html_preview,
        'social_package': {
            'linkedin_post': social_package.linkedin_post if social_package else '',
            'twitter_thread': social_package.twitter_thread if social_package else [],
            'newsletter': social_package.newsletter if social_package else '',
            'podcast_outline': social_package.podcast_outline if social_package else '',
        } if social_package else None
    }
    return JsonResponse(data)


@capability_required_api('publish_blog')
def approve_article_api(request, article_id):
    """Approves and automatically publishes article to live Teklora website."""
    if request.method == 'POST':
        article = get_object_or_404(EditorialArticle, pk=article_id)
        
        workflow = HumanApprovalWorkflow()
        workflow.approve_article(article)

        publisher = PublishingAgent()
        blog_post, pub_log = publisher.publish_approved_article(article)

        return JsonResponse({
            'status': 'published',
            'article_id': article.id,
            'blog_post_id': blog_post.id,
            'blog_post_url': blog_post.get_absolute_url()
        })
    return JsonResponse({'error': 'POST required'}, status=405)


@capability_required_api('publish_blog')
def reject_article_api(request, article_id):
    """Rejects draft article."""
    if request.method == 'POST':
        article = get_object_or_404(EditorialArticle, pk=article_id)
        workflow = HumanApprovalWorkflow()
        workflow.reject_article(article, reason="Rejected by editor via Dashboard")
        return JsonResponse({'status': 'rejected', 'article_id': article.id})
    return JsonResponse({'error': 'POST required'}, status=405)


@capability_required('manage_blog')
def export_docx_view(request, article_id):
    """Downloads Word DOCX document of the draft article."""
    article = get_object_or_404(EditorialArticle, pk=article_id)
    workflow = HumanApprovalWorkflow()
    docx_bytes = workflow.export_as_docx(article)

    response = HttpResponse(
        docx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="Teklora_Draft_{article.slug}.docx"'
    return response


@capability_required_api('manage_blog')
def semantic_search_api(request):
    """Searches vector knowledge base using pgvector embeddings."""
    q = request.GET.get('q', '')
    if not q:
        return JsonResponse({'results': []})

    agent = KnowledgeBaseAgent()
    docs = agent.semantic_search(q, limit=5)

    results = [{
        'id': d.id,
        'title': d.title,
        'doc_type': d.get_doc_type_display(),
        'content_snippet': d.content[:250],
        'metadata': d.metadata
    } for d in docs]

    return JsonResponse({'query': q, 'results': results})
