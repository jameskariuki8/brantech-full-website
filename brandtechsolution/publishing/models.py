from django.db import models
from django.utils import timezone
from editorial.models import EditorialArticle
from brand.models import BlogPost


class PublishingLog(models.Model):
    """Module 11: Publishing Audit Log"""
    article = models.OneToOneField(EditorialArticle, on_delete=models.CASCADE, related_name='publishing_log')
    blog_post = models.ForeignKey(BlogPost, on_delete=models.SET_NULL, null=True, blank=True, related_name='publishing_logs')
    
    published_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=30, default='published')
    channels_notified = models.JSONField(default=list, help_text="List of engines/channels notified e.g. Google, Bing, RSS")

    def __str__(self):
        return f"Published: '{self.article.title}' -> BlogPost #{self.blog_post_id}"
