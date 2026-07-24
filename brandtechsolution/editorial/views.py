import json
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from trends.models import TrendTopic, CompetitorArticle, TrendPrediction
from research.models import ResearchDossier, VerifiedFactReport
from editorial.models import EditorialArticle, SocialPackage
from editorial.orchestrator import EditorialPipelineOrchestrator
from approval.services.workflow import HumanApprovalWorkflow
from publishing.services.publisher import PublishingAgent
from knowledge_base.services.knowledge_graph import KnowledgeBaseAgent
from knowledge_base.models import KnowledgeDocument


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


@csrf_exempt
def trigger_pipeline_api(request):
    """API endpoint to manually trigger autonomous pipeline cycle."""
    if request.method == 'POST':
        try:
            body = json.loads(request.body.decode('utf-8')) if request.body else {}
            limit = int(body.get('limit', 1))
            auto_publish = bool(body.get('auto_publish', False))
        except Exception:
            limit = 1
            auto_publish = False

        orchestrator = EditorialPipelineOrchestrator()
        articles = orchestrator.run_full_autonomous_cycle(limit=limit, auto_publish=auto_publish)

        return JsonResponse({
            'status': 'success',
            'articles_processed': len(articles),
            'articles': [{'id': a.id, 'title': a.title, 'status': a.status} for a in articles]
        })
    return JsonResponse({'error': 'POST required'}, status=405)


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


@csrf_exempt
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


@csrf_exempt
def reject_article_api(request, article_id):
    """Rejects draft article."""
    if request.method == 'POST':
        article = get_object_or_404(EditorialArticle, pk=article_id)
        workflow = HumanApprovalWorkflow()
        workflow.reject_article(article, reason="Rejected by editor via Dashboard")
        return JsonResponse({'status': 'rejected', 'article_id': article.id})
    return JsonResponse({'error': 'POST required'}, status=405)


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
