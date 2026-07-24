from django.contrib import admin
from research.models import ResearchDossier, VerifiedFactReport


@admin.register(ResearchDossier)
class ResearchDossierAdmin(admin.ModelAdmin):
    list_display = ('topic', 'created_at')
    search_fields = ('topic__title', 'technical_explanations', 'african_opportunities')


@admin.register(VerifiedFactReport)
class VerifiedFactReportAdmin(admin.ModelAdmin):
    list_display = ('dossier', 'confidence_level', 'is_approved', 'created_at')
    list_filter = ('is_approved',)
