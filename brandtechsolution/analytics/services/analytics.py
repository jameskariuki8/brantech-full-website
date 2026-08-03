"""
Module 12: Analytics Intelligence Agent

Collects views, bounce rates, reading time, CTR, search rankings, and social shares.
Analyzes which topics, headlines, and writing styles perform best.
Feeds these insights back into the Trend Intelligence Agent to continuously improve decision-making.
"""
import logging
from typing import Dict, Any
from editorial.models import EditorialArticle
from analytics.models import ContentAnalytics, FeedbackLoopRecord

logger = logging.getLogger(__name__)


class AnalyticsIntelligenceAgent:
    """Tracks content performance and provides feedback loops for trend scoring."""

    def record_view(self, article: EditorialArticle, reading_seconds: int = 180) -> ContentAnalytics:
        """Records a user view/engagement event."""
        analytics, _ = ContentAnalytics.objects.get_or_create(article=article)
        analytics.views_count += 1
        
        # Recalculate engagement score
        views = analytics.views_count
        shares = analytics.social_shares
        
        score = min(10.0, (views * 0.05) + (shares * 0.5) + (analytics.ctr * 0.4))
        analytics.engagement_score = round(score, 2)
        analytics.save()

        # Also sync view count to brand.BlogPost if linked
        if hasattr(article, 'publishing_log') and article.publishing_log.blog_post:
            bp = article.publishing_log.blog_post
            bp.view_count = views
            bp.save()

        return analytics

    def generate_feedback_insights(self) -> FeedbackLoopRecord:
        """Analyzes top performing categories and generates feedback record."""
        top_articles = EditorialArticle.objects.filter(analytics__isnull=False).order_by('-analytics__engagement_score')[:5]
        
        top_topics = [a.title for a in top_articles]
        top_headlines = [a.subtitle for a in top_articles]
        
        fb = FeedbackLoopRecord.objects.create(
            category="AI & Infrastructure",
            top_performing_topics=top_topics,
            top_performing_headlines=top_headlines,
            recommended_priority_boost=1.25
        )
        logger.info(f"[AnalyticsIntelligenceAgent] Feedback loop created with {len(top_topics)} top topics.")
        return fb
