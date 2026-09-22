"""The model catalogue: what exists, what it can do, and what it costs.

Refreshed from the providers' own listings, which is also the call that
verifies a credential -- so activation and refresh are one operation.

Prices are the interesting part. Only OpenRouter publishes them, so the
catalogue takes them where it can and records where each one came from. A row
whose price came from OpenRouter is marked as such, because OpenRouter's price
is what OpenRouter charges to proxy a model and need not equal what the
provider charges directly. Good enough to choose a model by; not good enough to
bill from.
"""
import logging
import tomllib
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.utils import timezone

from brandtechsolution.config import config

from ai_workflows.harness.providers import ADAPTERS, get_adapter

logger = logging.getLogger(__name__)

PRICING_FILE = Path(__file__).with_name("pricing.toml")

# OpenRouter slugs the other providers' models. Mapping the prefix back lets a
# directly-configured provider inherit a price its own API never published.
OPENROUTER_PREFIXES = {
    "anthropic/": "anthropic",
    "openai/": "openai",
    "google/": "gemini",
    "deepseek/": "deepseek",
}


def load_manual_prices(path=PRICING_FILE):
    """Read the checked-in table.

    Returns {provider: {model_id: {"input": x, "output": y, "as_of": date}}}.
    A provider without an `as_of` is skipped: an undated price cannot be told
    apart from a checked one at the point it is read, so it is treated as
    absent rather than trusted.
    """
    if not path.exists():
        return {}

    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    out = {}
    for provider, block in raw.items():
        as_of = block.get("as_of")
        if as_of is None:
            logger.warning("[catalogue] %s prices have no as_of date; ignoring", provider)
            continue
        models = block.get("models") or {}
        out[provider] = {
            model_id: {**values, "as_of": as_of}
            for model_id, values in models.items()
        }
    return out


def _parse_deprecation(value):
    """A provider's retirement date, as an aware datetime.

    OpenRouter sends bare dates ("2026-09-28") with no offset, which Django
    stores with a RuntimeWarning and reads back ambiguously. A retirement date
    is a point in time, so an absent offset is treated as UTC rather than as
    local -- the alternative silently shifts every date by the server's zone.
    """
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=dt_timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def sync_provider(name, *, adapter=None):
    """Verify one provider and refresh its slice of the catalogue.

    Returns the Provider row. A provider with no credential is recorded as
    `absent` without a network call; one whose listing fails stays `candidate`
    with the error attached, so a bad key is visible rather than silent.
    """
    from ai_workflows.models import CatalogueEntry, Provider

    adapter = adapter or get_adapter(name)
    provider, _ = Provider.objects.get_or_create(
        name=name,
        defaults={
            "billing": adapter.billing,
            "preference": adapter.preference,
            "enabled": adapter.default_enabled,
        },
    )

    # OpenRouter's listing is public, so it is refreshable with no key at all.
    needs_key = not isinstance(adapter, type(ADAPTERS["openrouter"]))
    if needs_key and not adapter.has_credential():
        provider.status = Provider.ABSENT
        provider.last_checked_at = timezone.now()
        provider.last_error = ""
        provider.save()
        return provider

    try:
        models = adapter.list_models()
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        provider.status = Provider.CANDIDATE
        provider.last_checked_at = timezone.now()
        provider.last_error = f"{type(exc).__name__}: {exc}"[:500]
        provider.save()
        logger.warning("[catalogue] %s did not verify: %s", name, exc)
        return provider

    now = timezone.now()
    seen = []
    for info in models:
        if not info.model_id:
            continue
        seen.append(info.model_id)
        entry, _ = CatalogueEntry.objects.update_or_create(
            provider=name, model_id=info.model_id,
            defaults={
                "display_name": info.display_name or info.model_id,
                "context_tokens": info.context_tokens,
                "max_output_tokens": info.max_output_tokens,
                "capabilities": info.capabilities,
                "deprecated_at": _parse_deprecation(info.deprecated_at),
                "available": True,
                "refreshed_at": now,
            },
        )
        if adapter.publishes_pricing and info.input_price_per_mtok is not None:
            entry.input_price_per_mtok = info.input_price_per_mtok
            entry.output_price_per_mtok = info.output_price_per_mtok
            entry.price_source = CatalogueEntry.PROVIDER
            entry.price_checked_at = now
            entry.save()

    # A model that vanished from the listing is marked gone, not deleted --
    # invocation rows point at it.
    CatalogueEntry.objects.filter(provider=name, available=True).exclude(
        model_id__in=seen
    ).update(available=False, refreshed_at=now)

    provider.status = Provider.ACTIVE
    provider.last_checked_at = now
    provider.last_error = ""
    provider.save()
    return provider


def apply_manual_prices(prices=None):
    """Overlay the checked-in table.

    Applied after the listings so a hand-checked price from the vendor beats a
    derived one: a rate someone read off the provider's own pricing page is
    more authoritative than OpenRouter's proxy rate, even when it is older.
    """
    from ai_workflows.models import CatalogueEntry

    prices = load_manual_prices() if prices is None else prices
    applied = 0

    for provider, models in prices.items():
        for model_id, values in models.items():
            if values.get("input") is None:
                continue
            updated = CatalogueEntry.objects.filter(
                provider=provider, model_id=model_id,
            ).update(
                input_price_per_mtok=values["input"],
                output_price_per_mtok=values.get("output"),
                price_source=CatalogueEntry.MANUAL,
                price_checked_at=timezone.now(),
            )
            applied += updated
    return applied


def borrow_openrouter_prices():
    """Give directly-configured providers the prices their own APIs omit.

    OpenRouter lists `anthropic/claude-...`, `openai/gpt-...` and so on with
    per-token rates, so a model reachable both ways can take its price from
    there. Marked `openrouter`, never `provider`, because the number is
    OpenRouter's rather than the vendor's -- the distinction is the whole
    reason `price_source` exists.

    Only fills gaps. A price already known from the provider or the manual
    table is left alone.
    """
    from ai_workflows.models import CatalogueEntry

    borrowed = 0
    source_rows = CatalogueEntry.objects.filter(
        provider="openrouter", input_price_per_mtok__isnull=False,
    )

    for row in source_rows:
        for prefix, target_provider in OPENROUTER_PREFIXES.items():
            if not row.model_id.startswith(prefix):
                continue
            bare = row.model_id[len(prefix):]
            updated = CatalogueEntry.objects.filter(
                provider=target_provider,
            ).filter(
                price_source__in=[CatalogueEntry.UNKNOWN, CatalogueEntry.OPENROUTER],
            ).filter(
                model_id__in=[bare, f"models/{bare}"],
            ).update(
                input_price_per_mtok=row.input_price_per_mtok,
                output_price_per_mtok=row.output_price_per_mtok,
                price_source=CatalogueEntry.OPENROUTER,
                price_checked_at=timezone.now(),
            )
            borrowed += updated
    return borrowed


def refresh(providers=None):
    """Verify every provider and rebuild the catalogue.

    Order matters: listings first, then OpenRouter's prices are borrowed to
    fill gaps, then the manual table overlays both -- so a hand-checked vendor
    price always wins over a proxy rate.
    """
    names = providers or list(ADAPTERS)
    results = {}

    for name in names:
        results[name] = sync_provider(name)

    borrowed = borrow_openrouter_prices()
    manual = apply_manual_prices()

    logger.info(
        "[catalogue] refreshed %s provider(s); %s price(s) borrowed, %s from the table",
        len(names), borrowed, manual,
    )
    return {"providers": results, "borrowed": borrowed, "manual": manual}


def chosen_model(provider_name):
    """The model this deployment has chosen for `provider_name`, or "".

    Gemini falls back to `config.gemini_chat_model`, which is the choice this
    deployment has always had and the reason adding the other providers changes
    nothing for it. Every other provider must be told explicitly.
    """
    from ai_workflows.models import Provider

    row = Provider.objects.filter(name=provider_name).first()
    if row is not None and row.default_model:
        return row.default_model

    if provider_name == "gemini":
        return config.gemini_chat_model
    return ""


def model_is_serviceable(provider_name, model_id):
    """Is `model_id` still something we can send a request to?

    Checked against the catalogue rather than assumed, because the catalogue is
    refreshed from the provider's own listing and is therefore the first place
    a retirement shows up. A model absent from the catalogue entirely is
    allowed through: the operator may have chosen it before the first refresh,
    and refusing would make the catalogue a prerequisite for sending any
    request at all.
    """
    from ai_workflows.models import CatalogueEntry

    entry = CatalogueEntry.objects.filter(
        provider=provider_name, model_id=model_id,
    ).first()
    if entry is None:
        return True
    if not entry.available:
        return False
    if entry.deprecated_at and entry.deprecated_at <= timezone.now():
        return False
    return True


def can_serve(provider_name):
    """Does `provider_name` have what it needs to answer a request?

    Distinct from `Provider.usable`, which is about the catalogue. OpenRouter
    is the case that forces the distinction: its model listing is public, so it
    verifies and goes `active` with no key at all -- and then cannot serve a
    single request. Reporting that as ready would be a green light for
    something guaranteed to fail on first use, which is the class of misleading
    signal this harness keeps removing.
    """
    from ai_workflows.harness.providers import get_adapter

    try:
        return bool(get_adapter(provider_name).credential())
    except KeyError:
        # A Provider row with no adapter is a leftover from a rename. It cannot
        # serve anything, and saying so is better than raising here.
        logger.warning("[catalogue] no adapter for provider %r", provider_name)
        return False


def resolve(*, pinned=None, allow_fallback=True):
    """(provider, model_id) pairs to try, in preference order.

    A provider qualifies when it is enabled, verified, and has a model chosen
    for it. That last condition is the one that matters: the catalogue holds
    five hundred models, and picking one by heuristic is the sort of silent
    guess this harness exists to remove -- a wrong guess produces answers that
    look exactly like right ones, at a price nobody chose.

    So a provider with a working key and no chosen model is skipped and said
    so, once per resolution. That is a configuration gap with an obvious fix,
    not an outage.

    Returns a list so a caller that may fall over to the next candidate has
    one, and a single-element list when it may not.
    """
    from ai_workflows.models import Provider

    if pinned:
        return [pinned]

    if not Provider.objects.exists():
        # The catalogue has never been refreshed. Gemini is the configured
        # baseline -- `google_api_key` is the one credential `config` requires
        # -- so it has to work on a fresh install without anyone running a
        # management command first. Making the catalogue a *prerequisite* for
        # sending any request would turn a new deployment into a puzzle.
        #
        # Deliberately only when there are no rows at all. Once a refresh has
        # run, an operator disabling every provider means it, and quietly
        # re-enabling Gemini behind their back would be worse than failing.
        if can_serve("gemini"):
            logger.info(
                "[catalogue] no providers recorded yet; using the configured "
                "Gemini model. Run refresh_catalogue to enable the rest."
            )
            return [("gemini", config.gemini_chat_model)]
        return []

    candidates = []
    for provider in Provider.objects.order_by("preference", "name"):
        if not provider.usable:
            continue

        if not can_serve(provider.name):
            logger.info(
                "[catalogue] %s is verified but has no credential to serve "
                "requests with; skipping.", provider.name,
            )
            continue

        model_id = chosen_model(provider.name)
        if not model_id:
            logger.info(
                "[catalogue] %s is verified but has no chosen model; skipping. "
                "Set one with `manage.py providers --set %s=<model-id>`.",
                provider.name, provider.name,
            )
            continue

        if not model_is_serviceable(provider.name, model_id):
            logger.warning(
                "[catalogue] %s is set to %s, which the catalogue reports as "
                "unavailable or retired; skipping.",
                provider.name, model_id,
            )
            continue

        candidates.append((provider.name, model_id))

    return candidates[:1] if not allow_fallback else candidates
