from django.contrib import admin
from publishing.models import PublishingLog


@admin.register(PublishingLog)
class PublishingLogAdmin(admin.ModelAdmin):
    list_display = ('article', 'blog_post', 'status', 'published_at')
