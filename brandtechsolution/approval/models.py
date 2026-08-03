from django.db import models
from django.utils import timezone
from editorial.models import EditorialArticle


class ApprovalNotification(models.Model):
    """Module 10: Editor Notification Dispatch Record"""
    CHANNEL_CHOICES = [
        ('email', 'Email Dispatch'),
        ('telegram', 'Telegram Webhook'),
        ('whatsapp', 'WhatsApp Notification'),
        ('dashboard', 'Editorial Dashboard'),
    ]

    article = models.ForeignKey(EditorialArticle, on_delete=models.CASCADE, related_name='notifications')
    channel = models.CharField(max_length=30, choices=CHANNEL_CHOICES, default='dashboard')
    recipient = models.CharField(max_length=200, default='editor@teklora.co.ke')
    payload = models.JSONField(default=dict)
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"[{self.get_channel_display()}] Notification for '{self.article.title}'"
