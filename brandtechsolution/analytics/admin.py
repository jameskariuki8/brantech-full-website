from django.contrib import admin
from analytics.models import ContentAnalytics, FeedbackLoopRecord


@admin.register(ContentAnalytics)
class ContentAnalyticsAdmin(admin.ModelAdmin):
    list_display = ('article', 'views_count', 'engagement_score', 'ctr', 'last_updated')


@admin.register(FeedbackLoopRecord)
class FeedbackLoopRecordAdmin(admin.ModelAdmin):
    list_display = ('category', 'recommended_priority_boost', 'created_at')
