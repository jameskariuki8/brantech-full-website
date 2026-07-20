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
