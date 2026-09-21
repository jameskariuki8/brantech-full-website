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


class AgentProfile(models.Model):
    """How the company speaks, in one place.

    `EditorialMemory` held the brand voice and preferred terminology and was
    read only by the writer; the chat assistant had its own hardcoded system
    prompt that never consulted it. So the company had one brand voice and the
    codebase had two definitions of it, with no way for them to converge.

    A singleton, because "how do we speak" is not a per-row question. Seeded
    from EditorialMemory's values so adopting it changes nothing about what the
    writer produces.

    Read it with `load()`. A second `objects.create()` raises on the primary
    key rather than quietly succeeding -- two rows would reintroduce exactly
    the drift this replaces, so failing loudly is the desired behaviour.
    """

    SINGLETON_ID = 1

    brand_voice = models.TextField(
        default=(
            "Authoritative, forward-looking, technically grounded, "
            "African-centric, and accessible."
        )
    )
    preferred_terminology = models.JSONField(
        default=dict, blank=True,
        help_text="Mappings such as {'AI': 'Artificial Intelligence'}.",
    )
    excluded_topics = models.JSONField(default=list, blank=True)
    style_rules = models.JSONField(default=list, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Agent profile"
        verbose_name_plural = "Agent profile"

    def __str__(self):
        return "Teklora agent profile"

    def save(self, *args, **kwargs):
        # A second row would reintroduce exactly the ambiguity this replaces.
        self.pk = self.SINGLETON_ID
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        profile, _ = cls.objects.get_or_create(pk=cls.SINGLETON_ID)
        return profile


# ============================================================
# PROVIDERS AND THE MODEL CATALOGUE
# ============================================================


class Provider(models.Model):
    """One model provider, and whether it can actually be used.

    Three states, because "a key is present" and "a key works" are different
    things and conflating them is how a typo becomes a silent outage. A
    provider with a key starts as `candidate` and is promoted only once it has
    answered its own model-list endpoint.

    Never probed at import time -- config.py is imported by settings.py, and a
    network call there would make Django's startup depend on five third
    parties -- and never in the request path, which would double latency and
    burn rate limit.
    """

    ABSENT = 'absent'
    CANDIDATE = 'candidate'
    ACTIVE = 'active'
    STATUS_CHOICES = [
        (ABSENT, 'No credential configured'),
        (CANDIDATE, 'Credential present, not yet verified'),
        (ACTIVE, 'Verified'),
    ]

    USAGE = 'usage'
    SUBSCRIPTION = 'subscription'
    BILLING_CHOICES = [
        (USAGE, 'Billed per token'),
        (SUBSCRIPTION, 'Consumes a subscription seat'),
    ]

    name = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ABSENT)
    billing = models.CharField(max_length=20, choices=BILLING_CHOICES, default=USAGE)

    # Lower sorts first when resolving a role to a model. An operator reorders
    # preference here rather than in code.
    preference = models.PositiveSmallIntegerField(default=100)
    enabled = models.BooleanField(
        default=True,
        help_text="Off keeps a provider out of resolution even with a valid key.",
    )

    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['preference', 'name']

    def __str__(self):
        return f"{self.name} ({self.status})"

    @property
    def usable(self):
        return self.enabled and self.status == self.ACTIVE


class CatalogueEntry(models.Model):
    """One model a provider offers, with what it costs and what it can do.

    Refreshed from the providers' own listings. Of the five, only OpenRouter
    publishes pricing through its API -- unauthenticated, per token -- and it
    also lists the other four providers' models, which makes it the obvious
    metadata source. It is not an authoritative one: its prices are what
    OpenRouter charges to proxy a model, not what the provider charges
    directly. Hence `price_source`.
    """

    PROVIDER = 'provider'
    OPENROUTER = 'openrouter'
    MANUAL = 'manual'
    UNKNOWN = 'unknown'
    PRICE_SOURCE_CHOICES = [
        (PROVIDER, "The provider's own API"),
        (OPENROUTER, "Derived from OpenRouter's listing"),
        (MANUAL, 'Checked-in table'),
        (UNKNOWN, 'Not known'),
    ]

    provider = models.CharField(max_length=40, db_index=True)
    model_id = models.CharField(max_length=200)
    display_name = models.CharField(max_length=200, blank=True, default='')

    context_tokens = models.PositiveIntegerField(null=True, blank=True)
    max_output_tokens = models.PositiveIntegerField(null=True, blank=True)

    input_price_per_mtok = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True)
    output_price_per_mtok = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True)
    price_source = models.CharField(
        max_length=20, choices=PRICE_SOURCE_CHOICES, default=UNKNOWN)
    price_checked_at = models.DateTimeField(null=True, blank=True)

    capabilities = models.JSONField(default=dict, blank=True)
    deprecated_at = models.DateTimeField(null=True, blank=True)

    # A model that disappears from a listing is marked unavailable, never
    # deleted: invocation rows point at it, and history should not rewrite
    # itself because a vendor retired something.
    available = models.BooleanField(default=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['provider', 'model_id']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'model_id'], name='one_catalogue_entry_per_model',
            ),
        ]
        indexes = [models.Index(fields=['provider', 'available'])]
        verbose_name_plural = 'Catalogue entries'

    def __str__(self):
        return f"{self.provider}/{self.model_id}"

    @property
    def price_is_known(self):
        return self.input_price_per_mtok is not None

    @property
    def price_is_authoritative(self):
        """Whether the price came from the provider that will bill for it."""
        return self.price_source in (self.PROVIDER, self.MANUAL)

    def cost_for(self, prompt_tokens, completion_tokens):
        """What a call of this shape costs, or None when the price is unknown.

        None rather than zero: a model whose price nobody knows has not been
        established as free, and reporting it as free would quietly understate
        every total it appears in.
        """
        if self.input_price_per_mtok is None or self.output_price_per_mtok is None:
            return None
        million = 1_000_000
        return (
            float(self.input_price_per_mtok) * prompt_tokens / million
            + float(self.output_price_per_mtok) * completion_tokens / million
        )


class AgentHealth(models.Model):
    """Whether an agent is currently working, and whether anyone was told.

    Alerts fire on a *state change*, not per failure. A dead provider fails
    every stage of every run, so one message per failure would replace silence
    with a storm -- and a storm is worse than the silence it replaced, because
    people filter it.

    So: the first transition from healthy to failing sends; further failures of
    the same agent with the same error class are counted here and suppressed;
    recovery sends once. The suppressed count goes into the alert, so nobody
    has to guess whether they are seeing one blip or four hundred.
    """

    HEALTHY = 'healthy'
    FAILING = 'failing'
    STATUS_CHOICES = [(HEALTHY, 'Healthy'), (FAILING, 'Failing')]

    agent = models.CharField(max_length=60, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=HEALTHY)

    # The class name rather than the message: two ModelUnavailable failures are
    # the same outage even when their messages differ by a timestamp, while a
    # ModelUnavailable followed by an AgentOutputInvalid is a new problem worth
    # a second alert.
    error_class = models.CharField(max_length=80, blank=True, default='')
    error_message = models.TextField(blank=True, default='')

    failing_since = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_alert_at = models.DateTimeField(null=True, blank=True)
    suppressed_since_alert = models.PositiveIntegerField(default=0)

    # A send that failed is recorded rather than swallowed: an alert nobody
    # received is silence again by a different route.
    last_alert_error = models.TextField(blank=True, default='')

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['agent']
        verbose_name_plural = 'Agent health'

    def __str__(self):
        return f"{self.agent}: {self.status}"

    @property
    def is_failing(self):
        return self.status == self.FAILING
