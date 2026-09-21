"""Content-addressed step results, so a retry resumes instead of restarting.

A step's key is a digest of its name, the agent's fingerprint, and its inputs.
Same inputs and same agent means the stored result is reused; a changed
persona or schema changes the fingerprint and therefore the key, so edited
prompts are never served from cache.
"""
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


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

    def __init__(self, enabled=True, agent=""):
        self.enabled = enabled
        self.agent = agent

    def run(self, step, inputs, produce, fingerprint=""):
        """Return the stored result for these inputs, or produce and store it.

        A failure in `produce` is not cached. Caching an exception would turn a
        transient provider outage into a permanent one for those inputs.
        """
        from ai_workflows.models import StepResult

        if not self.enabled:
            return produce()

        key = step_key(step, inputs, fingerprint)

        existing = StepResult.objects.filter(key=key).first()
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

    def invalidate(self, step=None):
        """Drop cached results, for one step or all of them."""
        from ai_workflows.models import StepResult

        rows = StepResult.objects.all()
        if step:
            rows = rows.filter(step=step)
        return rows.delete()[0]
