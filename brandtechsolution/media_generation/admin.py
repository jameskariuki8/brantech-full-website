from django.contrib import admin
from media_generation.models import MediaAsset


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ('article', 'asset_type', 'alt_text', 'created_at')
    list_filter = ('asset_type',)
