from django.shortcuts import render
from staff.decorators import capability_required
from editorial.models.trends import TrendTopic, CompetitorArticle, TrendPrediction
from editorial.models import EditorialArticle
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
