from django.db import models


class EditorialMemory(models.Model):
    """Module 17: Editorial Memory Agent

    Remembers writing guidelines, tone rules, preferred brand vocabulary, and past covered topics.
    """
    brand_voice = models.TextField(default="Authoritative, forward-looking, technically grounded, African-centric, and accessible.")
    preferred_terminology = models.JSONField(default=dict, help_text="Key dictionary mappings, e.g. {'AI Agent': 'Autonomous AI Agent'}")
    seo_rules = models.JSONField(default=dict)
    excluded_topics = models.JSONField(default=list, help_text="Topics recently covered to avoid repetition")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Editorial Memory"

    def __str__(self):
        return "Teklora Editorial Memory & Guidelines"
