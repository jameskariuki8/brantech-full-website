from django.db import models
from django.utils import timezone
from editorial.models import EditorialArticle


class ContentAnalytics(models.Model):
    """Module 12: Analytics Intelligence Data Model"""
    article = models.OneToOneField(EditorialArticle, on_delete=models.CASCADE, related_name='analytics')
    
    views_count = models.PositiveIntegerField(default=0)
    bounce_rate = models.FloatField(default=35.0, help_text="Percentage")
    avg_reading_time_seconds = models.PositiveIntegerField(default=240)
    ctr = models.FloatField(default=4.5, help_text="Click-through rate %")
    social_shares = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    engagement_score = models.FloatField(default=7.5, help_text="Aggregated performance 0-10")
    
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Analytics ({self.views_count} views, Score: {self.engagement_score}): {self.article.title}"


class FeedbackLoopRecord(models.Model):
    """Stores AI self-learning feedback records fed into Trend Intelligence Agent."""
    category = models.CharField(max_length=100)
    top_performing_topics = models.JSONField(default=list)
    top_performing_headlines = models.JSONField(default=list)
    recommended_priority_boost = models.FloatField(default=1.2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback Loop for {self.category} ({self.created_at.strftime('%Y-%m-%d')})"
