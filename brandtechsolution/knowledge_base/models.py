from django.db import models
from django.utils import timezone
from pgvector.django import VectorField


class KnowledgeDocument(models.Model):
    """Module 13: Knowledge Base Agent

    Stores vector embeddings and structured text of every article, research paper,
    summary, trend, and source to allow future articles to reuse verified knowledge via RAG.
    """
    DOC_TYPES = [
        ('article', 'Published Article'),
        ('research_dossier', 'Research Dossier'),
        ('trend_summary', 'Trend Summary'),
        ('source_doc', 'External Reference Document'),
    ]

    title = models.CharField(max_length=300)
    doc_type = models.CharField(max_length=30, choices=DOC_TYPES, default='article')
    content = models.TextField()
    metadata = models.JSONField(default=dict, help_text="Source URL, tags, category, author info")
    
    # 3072 dimensions matching Gemini embedding-001 vector space
    embedding = VectorField(dimensions=3072, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_doc_type_display()}] {self.title}"
