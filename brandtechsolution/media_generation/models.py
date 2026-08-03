from django.db import models
from editorial.models import EditorialArticle


class MediaAsset(models.Model):
    """Module 8: Visual Intelligence Asset Record"""
    ASSET_TYPES = [
        ('hero_image', 'Hero Cover Image'),
        ('infographic', 'Infographic Diagram'),
        ('social_graphic', 'Social Media Card'),
        ('youtube_thumbnail', 'YouTube Thumbnail'),
    ]

    article = models.ForeignKey(EditorialArticle, on_delete=models.CASCADE, related_name='media_assets')
    asset_type = models.CharField(max_length=30, choices=ASSET_TYPES, default='hero_image')
    prompt = models.TextField(help_text="Detailed AI image generation prompt")
    image_file = models.ImageField(upload_to='generated_media/', blank=True, null=True)
    svg_content = models.TextField(blank=True, help_text="Generated SVG diagram code")
    alt_text = models.CharField(max_length=300)
    caption = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.get_asset_type_display()}] for {self.article.title}"
