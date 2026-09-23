from django.db import models
from django.utils import timezone
from trends.models import TrendTopic


class ResearchDossier(models.Model):
    """Stores structured research dossiers compiled by Research Agent (Module 3)."""
    topic = models.OneToOneField(TrendTopic, on_delete=models.CASCADE, related_name='dossier')
    
    key_concepts = models.JSONField(default=list, help_text="Core concepts and definitions")
    timeline = models.JSONField(default=list, help_text="Historical milestones and developments")
    technical_explanations = models.TextField(help_text="Deep architectural & technical breakdown")
    advantages_and_limitations = models.JSONField(default=dict, help_text="Pros and Cons")
    industry_applications = models.TextField(blank=True, help_text="Global industry use cases")
    african_opportunities = models.TextField(help_text="African ecosystem & startup opportunities")
    future_outlook = models.TextField(blank=True)
    sources = models.JSONField(default=list, help_text="List of verified reference URLs and citations")
    
    structured_dossier = models.TextField(help_text="Complete markdown research dossier")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Research Dossier: {self.topic.title}"


class VerifiedFactReport(models.Model):
    """Stores verified research after Fact Verification Agent processing (Module 4)."""
    dossier = models.OneToOneField(ResearchDossier, on_delete=models.CASCADE, related_name='verification_report')
    
    confidence_level = models.FloatField(default=0.9, help_text="Overall fact verification score (0-1)")
    contradictions_detected = models.JSONField(default=list, help_text="Identified discrepancies")
    unsupported_claims_removed = models.JSONField(default=list, help_text="Filtered out unverified claims")
    verified_statistics = models.JSONField(default=list, help_text="Cross-referenced statistics")
    verified_quotes = models.JSONField(default=list, help_text="Attributed expert quotes")
    
    verified_dossier = models.TextField(help_text="Final sanitized and verified research text")
    verification_evidence = models.TextField(
        blank=True, default="",
        help_text=(
            "What the agent found when it checked the dossier's sources: the "
            "tool calls it made and what came back. Separate from "
            "verified_dossier because that field is what the writer drafts "
            "from, and fetched source text must not reach the article prompt."
        ),
    )
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Fact Verification ({self.confidence_level*100:.0f}%): {self.dossier.topic.title}"
