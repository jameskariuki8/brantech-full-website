"""Content-addressed step results, so a retry resumes instead of restarting.

A step's key is a digest of its name, the agent's fingerprint, and its inputs.
Same inputs and same agent means the stored result is reused; a changed
persona or schema changes the fingerprint and therefore the key, so edited
prompts are never served from cache.
"""
import hashlib
import json
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

# How long a stored result stays usable.
#
# The cache exists so a failure at stage nine does not re-run stages one to
# eight -- a resume, measured in minutes. Without an expiry it is something
# else: a dossier researched three weeks ago would be served to a re-run today
# as though it were fresh, and "why is the article citing last month's news"
# has no visible cause. A day is comfortably longer than any retry loop and far
# shorter than the news cycle it would otherwise outlive.
DEFAULT_MAX_AGE = timedelta(hours=24)


def step_key(step, inputs, fingerprint=""):
    """A stable digest for one step invocation.

    `sort_keys` matters more than it looks: dict ordering is insertion order in
    Python, so without it the same inputs built in a different order would hash
    differently and every cache lookup would miss.
    """
    payload = json.dumps(
        {"step": step, "fingerprint": fingerprint, "inputs": inputs},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class StepCache:
    """Reads and writes StepResult rows.

    `enabled=False` turns it into a pass-through, which is what an eval run
    wants: measuring an agent whose answer came from cache measures the cache.
    """

    def __init__(self, enabled=True, agent="", max_age=DEFAULT_MAX_AGE):
        self.enabled = enabled
        self.agent = agent
        # None disables expiry, which a caller has to ask for rather than get
        # by leaving an argument out.
        self.max_age = max_age

    def _fresh(self, rows):
        from django.utils import timezone

        if self.max_age is None:
            return rows
        return rows.filter(created_at__gte=timezone.now() - self.max_age)

    def run(self, step, inputs, produce, fingerprint=""):
        """Return the stored result for these inputs, or produce and store it.

        A failure in `produce` is not cached. Caching an exception would turn a
        transient provider outage into a permanent one for those inputs.
        """
        from ai_workflows.models import StepResult

        if not self.enabled:
            return produce()

        key = step_key(step, inputs, fingerprint)

        existing = self._fresh(StepResult.objects.filter(key=key)).first()
        if existing is not None:
            logger.info("[steps] reusing %s (%s)", step, key[:12])
            return existing.value

        value = produce()

        # get_or_create rather than create: two workers racing on the same
        # inputs both produce, and the loser must not raise on the unique key.
        StepResult.objects.get_or_create(
            key=key,
            defaults={
                "step": step,
                "agent": self.agent,
                "fingerprint": fingerprint,
                "value": value,
            },
        )
        return value

    def remember_row(self, step, inputs, produce, fingerprint=""):
        """Cache a step that produces a database row, by primary key.

        `value` is a JSON column and the pipeline's stages return model
        instances, so the row itself cannot go in. Its identity can, and that is
        the useful half: the work was already done and saved, and what a resume
        needs is to find it again rather than to pay for it twice.

        A `None` from `produce` is *not* cached. A stage returning None is an
        agent declining, and a decline is usually thin evidence or an unlucky
        roll -- re-running it is exactly what a retry is for, and storing it
        would make one bad answer permanent for the life of the entry.

        A stored key whose row has since been deleted is treated as a miss and
        cleared, rather than raising. History gets tidied; a resume should not
        break because it did.
        """
        from ai_workflows.models import StepResult

        if not self.enabled:
            return produce()

        key = step_key(step, inputs, fingerprint)

        existing = self._fresh(StepResult.objects.filter(key=key)).first()
        if existing is not None:
            row = self._rehydrate(existing.value)
            if row is not None:
                logger.info("[steps] reusing %s (%s)", step, key[:12])
                return row
            logger.info(
                "[steps] %s was cached but its row is gone; running it again", step,
            )
            StepResult.objects.filter(key=key).delete()

        produced = produce()
        if produced is None or getattr(produced, "pk", None) is None:
            return produced

        StepResult.objects.update_or_create(
            key=key,
            defaults={
                "step": step,
                "agent": self.agent,
                "fingerprint": fingerprint,
                "value": {"model": produced._meta.label_lower, "pk": produced.pk},
            },
        )
        return produced

    @staticmethod
    def _rehydrate(value):
        from django.apps import apps

        if not isinstance(value, dict) or "model" not in value:
            return None
        try:
            model = apps.get_model(value["model"])
            return model.objects.filter(pk=value.get("pk")).first()
        except Exception as exc:  # noqa: BLE001 - a miss, not a failure
            logger.debug("[steps] could not rehydrate %s: %s", value, exc)
            return None

    def prune(self, older_than=None):
        """Drop entries too old to be served, so the table stays bounded.

        Called at the start of a cycle rather than scheduled separately: the
        work that writes these rows is the obvious place to tidy them, and a
        cleanup task nobody runs is a table that grows forever.
        """
        from django.utils import timezone

        from ai_workflows.models import StepResult

        older_than = older_than or self.max_age
        if older_than is None:
            return 0
        cutoff = timezone.now() - older_than
        return StepResult.objects.filter(created_at__lt=cutoff).delete()[0]

    def invalidate(self, step=None):
        """Drop cached results, for one step or all of them."""
        from ai_workflows.models import StepResult

        rows = StepResult.objects.all()
        if step:
            rows = rows.filter(step=step)
        return rows.delete()[0]
