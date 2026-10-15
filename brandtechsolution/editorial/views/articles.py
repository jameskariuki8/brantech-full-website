from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponse
from staff.decorators import capability_required, capability_required_api
from editorial.models import EditorialArticle
from editorial.services.approval import HumanApprovalWorkflow
from editorial.services.publishing import PublishingAgent


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
