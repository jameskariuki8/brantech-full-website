from django.contrib import admin
from trends.models import TrendTopic, CompetitorSource, CompetitorArticle, TrendPrediction


@admin.register(TrendTopic)
class TrendTopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'source', 'popularity_score', 'priority_score', 'status', 'created_at')
    list_filter = ('status', 'category', 'source')
    search_fields = ('title', 'summary', 'keywords')
    ordering = ('-priority_score', '-created_at')


@admin.register(CompetitorSource)
class CompetitorSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'site_url', 'is_active', 'last_scraped_at')


@admin.register(CompetitorArticle)
class CompetitorArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'competitor', 'content_gap_score', 'published_at')
    list_filter = ('competitor',)


@admin.register(TrendPrediction)
class TrendPredictionAdmin(admin.ModelAdmin):
    list_display = ('topic_name', 'category', 'timeframe', 'confidence_score', 'created_at')
