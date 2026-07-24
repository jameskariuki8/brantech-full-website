from django.contrib import admin
from editorial.models import EditorialArticle, SocialPackage, EditorialMemory


@admin.register(EditorialArticle)
class EditorialArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'target_audience', 'status', 'reading_time_minutes', 'created_at')
    list_filter = ('status', 'target_audience')
    search_fields = ('title', 'executive_summary', 'technical_explanation')
    prepopulated_fields = {'slug': ('title',)}


@admin.register(SocialPackage)
class SocialPackageAdmin(admin.ModelAdmin):
    list_display = ('article', 'created_at')


@admin.register(EditorialMemory)
class EditorialMemoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'updated_at')
