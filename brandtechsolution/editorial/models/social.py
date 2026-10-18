from django.db import models
from editorial.models.article import EditorialArticle


class SocialPackage(models.Model):
    """Module 9: Multi-Platform Content Agent Package

    Generates social posts, threads, newsletters, video scripts, and presentation slides
    from a single article.
    """
    article = models.OneToOneField(EditorialArticle, on_delete=models.CASCADE, related_name='social_package')

    linkedin_post = models.TextField()
    linkedin_article = models.TextField()
    twitter_thread = models.JSONField(default=list, help_text="List of tweets in thread")
    facebook_post = models.TextField()
    instagram_carousel = models.JSONField(default=list, help_text="Slide titles and bullet captions")
    
    newsletter = models.TextField(help_text="Email newsletter edition format")
    medium_article = models.TextField()
    devto_article = models.TextField()
    
    podcast_outline = models.TextField()
    youtube_script = models.TextField()
    tiktok_script = models.TextField()
    executive_summary_one_pager = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Social Ecosystem Package for: {self.article.title}"
