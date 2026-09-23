"""Waiting, when waiting is the right answer.

Not every refusal is an outage. A provider that answers "retry in 52s" has
told you it *will* answer, and treating that as a dead provider throws away
the one useful thing it said. The failover added after the first live eval run
did exactly that: it moved on, found no second provider configured, and
reported the writer as unable to work -- over a limit that would have cleared
itself while somebody read the error.

The distinction that matters is whether the limit clears on its own:

* **Per-minute** rate limits do. They are the free tier's normal working
  condition, not a fault, and the right response is to wait the stated delay.
* **Per-day** quotas do not. Gemini reports both as 429 and puts a ~30s
  `retryDelay` on both, so honouring that delay blindly would mean sleeping
  half a minute to be refused again, four more times. The `quotaId` is what
  separates them, so that is what this reads.
* **503 overloaded** clears on its own too, usually faster, and carries no
  delay of its own.

Waiting is bounded by a policy rather than a constant because the right
ceiling depends on who is waiting. A newsroom task run by a worker can afford
a minute; a visitor watching a chat box cannot, and would read it as the site
being broken.
"""
import logging
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# "retryDelay": "52s", and the prose form the same errors also carry.
_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)\s*s", re.I)
_RETRY_PROSE = re.compile(r"retry in\s+(\d+(?:\.\d+)?)\s*s", re.I)

# A quota that resets with the calendar, not with the clock. Waiting out a
# daily limit is not a retry, it is tomorrow.
_DAILY = re.compile(r"PerDay", re.I)

# Matched case-sensitively, and anchored on the tokens providers actually put
# in a status: `RESOURCE_EXHAUSTED`, `UNAVAILABLE`, a bare status code.
#
# An earlier version matched these case-insensitively, which quietly turned
# every `ModelUnavailable` and `MemoryUnavailable` in the codebase into a
# retryable refusal: the suite started sleeping five seconds per raise and
# took ten minutes instead of ninety seconds. A pattern loose enough to match
# an exception's own class name is not reading the provider, it is reading
# the English language.
_RATE_LIMITED = re.compile(r"RESOURCE_EXHAUSTED|\b429\b|\brate limit", re.I)
_OVERLOADED = re.compile(r"\b503\b|\bUNAVAILABLE\b|\boverloaded\b|high demand")

# Used when a provider rate-limits without saying for how long. Long enough to
# clear a per-minute window, short enough that a spent policy is not a
# noticeable part of a run.
DEFAULT_PAUSE = 20.0
OVERLOADED_PAUSE = 5.0


@dataclass(frozen=True)
class RetryPolicy:
    """How long a caller is willing to wait, and how often."""

    attempts: int = 0
    max_wait: float = 0.0

    @property
    def waits(self) -> bool:
        return self.attempts > 0 and self.max_wait > 0


# A background agent: a newsroom cycle takes minutes anyway, and the free
# tier's five-per-minute window is its normal working condition.
BATCH = RetryPolicy(attempts=4, max_wait=65.0)

# Somebody is watching a chat box. One short wait covers a momentary spike;
# more than that and they are looking at a site that appears broken, so the
# assistant is better off failing over or saying so.
INTERACTIVE = RetryPolicy(attempts=1, max_wait=6.0)

# Nothing waits.
NEVER = RetryPolicy()


def retry_after(exc) -> float | None:
    """Seconds to wait before retrying `exc`, or None if waiting will not help.

    None means "this provider is not going to answer": a revoked key, a
    malformed request, or a daily quota that a wait cannot restore.
    """
    message = str(exc)

    if _DAILY.search(message):
        # The delay attached to a daily quota error is not a lie exactly, but
        # honouring it means sleeping and being refused again.
        return None

    if _RATE_LIMITED.search(message):
        # A daily quota has already returned above, so anything still here
        # is a window that closes on the clock.
        stated = _stated_delay(message)
        return stated if stated is not None else DEFAULT_PAUSE

    if _OVERLOADED.search(message):
        return _stated_delay(message) or OVERLOADED_PAUSE

    return None


def _stated_delay(message):
    for pattern in (_RETRY_DELAY, _RETRY_PROSE):
        found = pattern.search(message)
        if found:
            return float(found.group(1))
    return None


def call_with_retries(call, *, policy=BATCH, label="", agent=None, sleep=None):
    """Run `call()`, waiting out a self-clearing refusal.

    Re-raises the provider's own exception once the policy is spent, so the
    caller's failover sees the real reason rather than a wrapper about
    retries.

    `sleep` is looked up at call time rather than bound as a default, so that
    patching `time.sleep` works. A default argument would capture the real one
    at import, and a test that thought it had stubbed the wait would instead
    stall the suite for the length of a provider's rate-limit window --
    which is exactly what the first version of this did.
    """
    sleep = sleep or time.sleep
    attempt = 0

    while True:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - re-raised unless we wait
            if not policy.waits or attempt >= policy.attempts:
                raise

            delay = retry_after(exc)
            if delay is None or delay > policy.max_wait:
                # Either waiting will not help, or it would take longer than
                # this caller has. Both mean: hand it to the failover.
                raise

            attempt += 1
            logger.info(
                "[retry] %s asked %s to wait %.1fs (attempt %s of %s)",
                label or "the provider", agent or "an agent", delay,
                attempt, policy.attempts,
            )
            sleep(delay)
