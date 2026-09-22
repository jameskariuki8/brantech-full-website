"""What each call consumed, and what it cost.

The harness had one ceiling: `Supervisor`'s dispatch counter. It counts agents,
not tokens, so it catches a routing loop and nothing else -- one agent making
forty long calls inside a single dispatch reads as one dispatch, and the thing
that discovers it is the invoice. `BudgetExceeded` was named for a budget that
did not exist.

Three pieces here.

**Extraction** reads the token counts off a response. LangChain normalises
these onto `usage_metadata`, which is the only shape worth relying on; the
older per-vendor dictionaries are read as a fallback and not trusted further
than that.

**Pricing** asks the catalogue. It answers `None` for a model nobody has
priced, and `None` is carried all the way through rather than being flattened
to zero -- an unpriced call is not a free one, and a total that quietly
included it as zero would be wrong in the direction that looks reassuring.

**A ledger**, held in a `ContextVar`. The alternative was threading a `run_id`
down through `Supervisor` -> `Agent.execute` -> `contract.ask` -> `_ask_one`,
four layers of parameter that exist only for bookkeeping, where every new call
site is a chance to forget it and under-report. A context variable is scoped to
the task that set it, which is exactly the boundary a run has.

Nothing in here may raise into a caller. Accounting that can take down the work
it accounts for is worse than no accounting: the failure would be attributed to
the agent, and the fix would be to remove the metering.
"""
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# Extraction
# ============================================================


@dataclass(frozen=True)
class Usage:
    """Token counts from one response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0

    @property
    def measured(self) -> bool:
        return self.total_tokens > 0 or self.prompt_tokens > 0


def usage_of(response) -> Usage | None:
    """Token counts from a model response, or None when it did not report any.

    None rather than a zeroed `Usage`: "this call reported nothing" and "this
    call used nothing" are different findings, and a row of zeros in the table
    would be indistinguishable from a free call.

    `with_structured_output` hands back the parsed object and drops the message
    that carried the counts, which is why `contract` binds it with
    `include_raw=True` -- otherwise the single most common call path in the
    codebase would be the one path that reported nothing.
    """
    if response is None:
        return None

    meta = getattr(response, "usage_metadata", None)
    if isinstance(meta, dict) and meta:
        prompt = int(meta.get("input_tokens") or 0)
        completion = int(meta.get("output_tokens") or 0)
        total = int(meta.get("total_tokens") or 0) or (prompt + completion)
        return Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            # Billed at the output rate, and worth separating because it is
            # invisible: on the probe that prompted this module, 89 of 124
            # output tokens were reasoning.
            reasoning_tokens=int(
                (meta.get("output_token_details") or {}).get("reasoning") or 0
            ),
            cached_tokens=int(
                (meta.get("input_token_details") or {}).get("cache_read") or 0
            ),
        )

    # The pre-normalisation shapes, read but not relied on.
    legacy = (getattr(response, "response_metadata", None) or {})
    for key in ("token_usage", "usage"):
        block = legacy.get(key)
        if not isinstance(block, dict) or not block:
            continue
        prompt = int(block.get("prompt_tokens") or block.get("input_tokens") or 0)
        completion = int(
            block.get("completion_tokens") or block.get("output_tokens") or 0
        )
        if not (prompt or completion):
            continue
        return Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=int(block.get("total_tokens") or 0) or prompt + completion,
        )

    return None


def model_name_of(response, default=""):
    """What the provider says answered, preferred over what we asked for.

    These differ in practice -- an alias resolves to a dated snapshot -- and
    the one that bills is the one that answered.
    """
    meta = getattr(response, "response_metadata", None) or {}
    return meta.get("model_name") or meta.get("model") or default


# ============================================================
# Pricing
# ============================================================


def normalise_model_id(model_id: str) -> str:
    """Strip the prefix Gemini's listing carries and its callers do not.

    The catalogue stores `models/gemini-2.5-flash` because that is what the
    listing endpoint returns; `Provider.default_model` holds `gemini-2.5-flash`
    because that is what the client is constructed with. Matching on the raw
    string misses, and a miss here is silent -- it reads as "this model has no
    price", which is indistinguishable from a model that genuinely has none.
    """
    return (model_id or "").strip().removeprefix("models/")


def price_for(provider, model_id):
    """The catalogue entry that prices this model, or None.

    Both spellings are tried, because which one reaches this depends on whether
    the caller got it from the catalogue or from the client.
    """
    from django.db.models import Q

    from ai_workflows.models import CatalogueEntry

    bare = normalise_model_id(model_id)
    if not bare:
        return None

    try:
        return (
            CatalogueEntry.objects
            .filter(provider=provider)
            .filter(Q(model_id=bare) | Q(model_id=f"models/{bare}"))
            .first()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[usage] could not look up a price: %s", exc)
        return None


def cost_of(usage, provider, model_id):
    """(cost_usd, price_source) for a call, cost None when unpriced.

    Reasoning tokens are already inside `completion_tokens` and are charged at
    the output rate, so they need no separate term; they are recorded
    separately only so a surprising bill can be explained.
    """
    entry = price_for(provider, model_id)
    if entry is None:
        return None, ""
    cost = entry.cost_for(usage.prompt_tokens, usage.completion_tokens)
    return cost, (entry.price_source if cost is not None else "")


# ============================================================
# The ledger
# ============================================================


@dataclass
class Ledger:
    """Running totals for one unit of work.

    Three counters rather than one, because "spent nothing" has three very
    different causes and a single number cannot tell them apart:

    - `spend_usd` is what the priced calls came to.
    - `unpriced_calls` is calls that ran against a model with no known price.
      Their cost is not zero; it is unknown, and `complete` is how a reader
      finds out before quoting the total.
    - `unmeasured_calls` is calls whose response reported no token counts at
      all, so not even the tokens are known.
    """

    label: str = ""
    run_id: int | None = None

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    spend_usd: float = 0.0
    unpriced_calls: int = 0
    unmeasured_calls: int = 0

    by_agent: dict = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def complete(self) -> bool:
        """Whether `spend_usd` is the whole bill or only the part we can see."""
        return not self.unpriced_calls and not self.unmeasured_calls

    def add(self, *, agent="", usage=None, cost=None):
        self.calls += 1
        if usage is None:
            self.unmeasured_calls += 1
        else:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens

        if cost is None:
            self.unpriced_calls += 1
        else:
            self.spend_usd += cost

        bucket = self.by_agent.setdefault(
            agent or "unattributed", {"calls": 0, "tokens": 0, "spend_usd": 0.0},
        )
        bucket["calls"] += 1
        bucket["tokens"] += usage.total_tokens if usage else 0
        bucket["spend_usd"] += cost or 0.0

    def summary(self) -> str:
        spend = f"${self.spend_usd:.4f}"
        if not self.complete:
            unknown = []
            if self.unpriced_calls:
                unknown.append(f"{self.unpriced_calls} unpriced")
            if self.unmeasured_calls:
                unknown.append(f"{self.unmeasured_calls} unmeasured")
            spend += f" plus {' and '.join(unknown)}"
        return f"{self.calls} calls, {self.tokens} tokens, {spend}"


_ACTIVE: ContextVar = ContextVar("ai_workflows_usage_ledger", default=None)


def active_ledger():
    return _ACTIVE.get()


@contextmanager
def accounting(ledger=None, *, label="", run_id=None):
    """Attribute every model call made inside this block to one ledger.

    Nests: an inner block replaces the outer one for its duration and restores
    it on the way out, so a supervisor run containing an agent that opens its
    own does not lose the outer total -- it simply does not see the inner
    calls, which is the behaviour a caller asking for a separate ledger wants.
    """
    ledger = ledger if ledger is not None else Ledger(label=label, run_id=run_id)
    token = _ACTIVE.set(ledger)
    try:
        yield ledger
    finally:
        _ACTIVE.reset(token)


# ============================================================
# Recording
# ============================================================


def record(response, *, provider, model, agent="", role="", run_id=None, label=""):
    """Account for one call, and return the row written (or None).

    Every failure path here is swallowed and logged. A `ModelInvocation` that
    could not be written is a gap in a report; an exception raised from here
    would be a gap in the article, attributed to the agent, and the obvious fix
    would be to stop metering.
    """
    try:
        usage = usage_of(response)
        served_by = normalise_model_id(model_name_of(response, model))

        cost, source = (None, "")
        if usage is not None:
            cost, source = cost_of(usage, provider, served_by)

        ledger = active_ledger()
        if ledger is not None:
            ledger.add(agent=agent, usage=usage, cost=cost)
            label = label or ledger.label
            run_id = run_id if run_id is not None else ledger.run_id

        if usage is None:
            logger.debug(
                "[usage] %s/%s reported no token counts for %s",
                provider, served_by, agent or role or "a call",
            )
            return None

        from ai_workflows.models import ModelInvocation

        return ModelInvocation.objects.create(
            provider=provider or "",
            model_id=served_by,
            agent=agent or "",
            role=str(role or ""),
            label=label or "",
            run_id=run_id,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cached_tokens=usage.cached_tokens,
            cost_usd=cost,
            price_source=source,
        )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning("[usage] could not record an invocation: %s", exc)
        return None


# ============================================================
# Reporting
# ============================================================


def totals(*, since=None, agent=None, label=None, run_id=None):
    """Aggregate recorded spend, and say how much of it is actually known.

    Returns the same shape as a `Ledger` so a live run and a historical query
    read the same way.
    """
    from django.db.models import Count, Q, Sum

    from ai_workflows.models import ModelInvocation

    rows = ModelInvocation.objects.all()
    if since is not None:
        rows = rows.filter(created_at__gte=since)
    if agent:
        rows = rows.filter(agent=agent)
    if label:
        rows = rows.filter(label=label)
    if run_id is not None:
        rows = rows.filter(run_id=run_id)

    figures = rows.aggregate(
        calls=Count("id"),
        prompt=Sum("prompt_tokens"),
        completion=Sum("completion_tokens"),
        spend=Sum("cost_usd"),
        unpriced=Count("id", filter=Q(cost_usd__isnull=True)),
    )

    ledger = Ledger(label=label or "", run_id=run_id)
    ledger.calls = figures["calls"] or 0
    ledger.prompt_tokens = figures["prompt"] or 0
    ledger.completion_tokens = figures["completion"] or 0
    ledger.spend_usd = float(figures["spend"] or 0.0)
    ledger.unpriced_calls = figures["unpriced"] or 0
    return ledger
