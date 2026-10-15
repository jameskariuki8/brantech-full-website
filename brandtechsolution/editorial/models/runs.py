from django.db import models
from editorial.models.article import EditorialArticle


class EditorialPipelineRun(models.Model):
    """One execution of the autonomous newsroom pipeline.

    The pipeline used to run inline in the request that triggered it, which
    meant a roughly three-minute HTTP call: Cloudflare cut the connection at
    100s and the browser reported a JSON parse error while the work carried on
    invisibly to completion. The run now happens in a Celery task and this row
    is how the dashboard follows it.

    Deliberately a model rather than Celery's result backend: results expire
    and carry no structure, and the newsroom wants a durable history of what
    ran, what it produced and how it failed.
    """

    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('success', 'Completed'),
        ('failed', 'Failed'),
    ]

    # Ordered, so the dashboard can render a progress bar rather than a
    # spinner. Keys are written by the orchestrator's stage callback.
    STAGES = [
        ('discovery', 'Discovering global trends'),
        ('intelligence', 'Scoring and prioritising topics'),
        ('secondary', 'Competitor gaps and forecasts'),
        ('research', 'Deep research dossier'),
        ('verification', 'Fact verification'),
        ('strategy', 'Editorial strategy'),
        ('writing', 'Drafting the article'),
        ('seo', 'SEO optimisation'),
        ('visual', 'Visual assets'),
        ('social', 'Social package'),
        ('handoff', 'Editor handoff'),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    stage = models.CharField(max_length=40, blank=True)
    stage_label = models.CharField(max_length=200, blank=True)

    limit = models.PositiveIntegerField(default=1)
    auto_publish = models.BooleanField(default=False)

    # Null for a run started by Beat rather than a person.
    triggered_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pipeline_runs',
    )

    task_id = models.CharField(max_length=255, blank=True, db_index=True)
    articles = models.ManyToManyField(EditorialArticle, blank=True, related_name='pipeline_runs')
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f"Pipeline run #{self.pk} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        return self.status in ('success', 'failed')

    @property
    def stage_index(self) -> int:
        """1-based position of the current stage, 0 when not started."""
        keys = [key for key, _ in self.STAGES]
        return keys.index(self.stage) + 1 if self.stage in keys else 0

    def mark_stage(self, key: str, label: str = "") -> None:
        """Record progress. Kept to the two columns so it is one cheap UPDATE
        per stage -- this is called from inside a long task, between model
        calls that each take several seconds."""
        self.stage = key
        self.stage_label = label or dict(self.STAGES).get(key, key)
        self.status = 'running'
        self.save(update_fields=['stage', 'stage_label', 'status'])
