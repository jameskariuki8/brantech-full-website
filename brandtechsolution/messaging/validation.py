"""Email address validation: cheap syntax checks and cached MX lookups.

Syntax validation is instant and runs wherever recipients are created. MX
lookups touch the network and are therefore never run implicitly -- they are
driven by an explicit admin action (see validate_campaign_recipients).
"""

import logging

import dns.exception
import dns.resolver
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

logger = logging.getLogger(__name__)

MX_TIMEOUT_SECONDS = 5
MX_CACHE_SECONDS = 3600


def validate_syntax(email):
    """True if `email` is a syntactically well-formed address. Never raises."""
    if not email:
        return False
    try:
        validate_email(email)
    except ValidationError:
        return False
    return True


def _query_mx(domain):
    """Resolve MX records for `domain`. The single DNS seam -- tests patch this."""
    resolver = dns.resolver.Resolver()
    resolver.timeout = MX_TIMEOUT_SECONDS
    resolver.lifetime = MX_TIMEOUT_SECONDS
    return resolver.resolve(domain, "MX")


def domain_has_mx(domain):
    """True if `domain` publishes at least one MX record.

    Results (positive and negative alike) are cached per domain: a recipient
    list of 500 addresses is typically a handful of distinct domains, and
    without caching that would be 500 network round trips.

    Any DNS failure -- NXDOMAIN, no answer, dead nameserver, timeout -- is
    reported as False rather than raised. A caller triggered by an admin
    button must not 500 because a nameserver was slow.
    """
    domain = (domain or "").strip().lower()
    if not domain:
        return False

    key = f"messaging:mx:{domain}"
    cached = cache.get(key)
    # A cached False is a real verdict, so test for the miss sentinel itself
    # rather than for falseness.
    if cached is not None:
        return cached

    try:
        answers = _query_mx(domain)
        result = bool(answers)
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.exception.Timeout,
    ):
        result = False
    except Exception as exc:  # noqa: BLE001 - a lookup failure is not an outage
        logger.warning("MX lookup failed for %s: %s", domain, exc)
        result = False

    cache.set(key, result, MX_CACHE_SECONDS)
    return result


def validate_campaign_recipients(campaign):
    """Run the MX pass over one campaign's recipients and return status counts.

    Rows already flagged `invalid_syntax` are left alone -- there is no domain
    worth looking up in a malformed address. Everything else is re-checked and
    stamped, so re-running the pass refreshes a stale verdict.
    """
    from .models import CampaignRecipient

    now = timezone.now()
    rows = CampaignRecipient.objects.filter(campaign=campaign).exclude(
        validation_status="invalid_syntax"
    )

    for row in rows:
        domain = (row.email or "").rsplit("@", 1)[-1]
        row.validation_status = "valid" if domain_has_mx(domain) else "invalid_domain"
        row.validated_at = now
        row.save(update_fields=["validation_status", "validated_at"])

    counts = {"valid": 0, "invalid_syntax": 0, "invalid_domain": 0, "unknown": 0}
    for status in CampaignRecipient.objects.filter(campaign=campaign).values_list(
        "validation_status", flat=True
    ):
        if status in counts:
            counts[status] += 1
    return counts
