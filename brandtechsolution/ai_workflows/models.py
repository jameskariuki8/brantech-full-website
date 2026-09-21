from django.db import models
from django.contrib.auth.models import User
from pydantic import BaseModel
from typing import Optional

class ConversationThread(models.Model):
    """Represents a conversation or workflow thread"""
    
    WORKFLOW_CHOICES = [
        ('chatbot', 'Chatbot Conversation'),
        ('blog_generation', 'Blog Generation'),
        ('content_enhancement', 'Content Enhancement'),
    ]
    
    thread_id = models.CharField(max_length=255, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    workflow_type = models.CharField(
        max_length=50,
        choices=WORKFLOW_CHOICES,
        default='chatbot'
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['thread_id']),
            models.Index(fields=['user', 'workflow_type']),
        ]
    
    def __str__(self):
        return f"{self.thread_id} ({self.workflow_type})"


class ConversationCheckpoint(models.Model):
    """Stores LangGraph checkpoint data"""
    
    thread = models.ForeignKey(
        ConversationThread,
        on_delete=models.CASCADE,
        related_name='checkpoints'
    )
    checkpoint_id = models.CharField(max_length=255, db_index=True)
    parent_checkpoint = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )
    
    # LangGraph state data (serialized)
    state = models.JSONField()
    
    # Metadata for querying and filtering
    checkpoint_metadata = models.JSONField(default=dict, blank=True)
    
    # Version tracking
    version = models.IntegerField(default=1)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = [['thread', 'checkpoint_id']]
        indexes = [
            models.Index(fields=['thread', 'checkpoint_id']),
            models.Index(fields=['thread', '-created_at']),
        ]
    
    def __str__(self):
        return f"Checkpoint {self.checkpoint_id[:8]}... ({self.thread.thread_id})"


class WorkflowState(models.Model):
    """Stores workflow-specific state (e.g., blog generation progress)"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    thread = models.OneToOneField(
        ConversationThread,
        on_delete=models.CASCADE,
        related_name='workflow_state'
    )
    current_step = models.CharField(max_length=100, default='')
    progress_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    error_message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.thread.thread_id} - {self.status}"

# ============================================================
# EVALS
# ============================================================
# Step 0 of the agent harness (docs/superpowers/specs/
# 2026-09-21-unified-agent-harness-design.md). Tests answer "did it run";
# these answer "was the output any good", which nothing in this codebase
# could do before. They exist first so that every later step of the harness
# migration can be shown not to have made the output worse -- and they have
# to be measured against the agents as they are today, because once those are
# rewritten there is nothing left to compare against.


class EvalRun(models.Model):
    """One execution of the eval suite.

    Kept as a row rather than a log line because the whole point is comparison:
    a run is only meaningful next to the run before it, and the baseline run
    captured before the migration is the permanent reference.
    """

    STATUS_CHOICES = [
        ('running', 'Running'),
        ('complete', 'Complete'),
        ('failed', 'Failed'),
    ]

    label = models.CharField(
        max_length=120, blank=True, default='',
        help_text="What was being measured, e.g. 'baseline' or 'native-structured-output'.",
    )
    is_baseline = models.BooleanField(
        default=False,
        help_text="The reference other runs are compared against.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')

    # Which agents this run covered; a partial run must not be mistaken for a
    # full one when its score is compared against another.
    agents = models.JSONField(default=list)
    samples_per_case = models.PositiveSmallIntegerField(default=1)

    git_sha = models.CharField(max_length=40, blank=True, default='')
    error = models.TextField(blank=True, default='')

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [models.Index(fields=['-started_at']), models.Index(fields=['is_baseline'])]

    def __str__(self):
        return f"Eval run #{self.pk} ({self.label or self.status})"

    @property
    def score(self):
        """Mean score across every result, or None when there are none."""
        scores = [r.score for r in self.results.all() if r.score is not None]
        return sum(scores) / len(scores) if scores else None

    def score_for(self, agent):
        scores = [r.score for r in self.results.all()
                  if r.agent == agent and r.score is not None]
        return sum(scores) / len(scores) if scores else None


class EvalResult(models.Model):
    """One case, graded, on one sample.

    Several rows per case when `samples_per_case` is above one: the writer
    runs at a non-zero temperature, so a single sample measures a noisy
    process once and reports the noise as a result. The spread across samples
    is itself a finding.
    """

    run = models.ForeignKey(EvalRun, related_name='results', on_delete=models.CASCADE)
    agent = models.CharField(max_length=60, db_index=True)
    case = models.CharField(max_length=120)
    sample = models.PositiveSmallIntegerField(default=0)
    grader = models.CharField(max_length=60)

    # None when the grader could not reach a verdict -- distinct from 0.0,
    # which is a verdict of "wrong".
    score = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(null=True)
    detail = models.TextField(blank=True, default='')
    output = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['agent', 'case', 'sample']
        indexes = [models.Index(fields=['run', 'agent'])]

    def __str__(self):
        return f"{self.agent}/{self.case}#{self.sample}: {self.score}"


class StepResult(models.Model):
    """One agent step's output, keyed by what produced it.

    The editorial pipeline is eleven stages and several model calls over
    roughly three minutes. A failure at stage nine re-runs stages one to eight
    -- paid for again, and a three-minute wait for every iteration on the
    failing stage. Three services already reach for this by hand, looking up an
    `existing` row before working, which is accidental idempotency applied
    inconsistently.

    The key includes the agent's fingerprint, not just the inputs. Without
    that, editing a persona or a schema would reuse results produced by the old
    one and prompt work would appear to do nothing -- which is a genuinely
    miserable thing to debug.
    """

    key = models.CharField(max_length=64, unique=True, db_index=True)
    step = models.CharField(max_length=120, db_index=True)
    agent = models.CharField(max_length=60, blank=True, default='')
    fingerprint = models.CharField(
        max_length=32, blank=True, default='',
        help_text="Digest of the agent version that produced this.",
    )

    value = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['step', '-created_at'])]

    def __str__(self):
        return f"{self.step} [{self.key[:12]}]"
