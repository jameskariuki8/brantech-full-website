"""Cloudflare Turnstile verification for the public forms.

Turnstile rather than reCAPTCHA because the site already runs behind a
Cloudflare Tunnel, so it adds no new vendor, no new account and no tracking
cookie for visitors. The contract is the same as every CAPTCHA: the browser
solves a challenge, posts a token with the form, and the server asks
Cloudflare whether that token is genuine.

Three rules hold here:

1. The check happens on the SERVER. The widget in the page is only how a
   token gets minted - a bot can skip the page entirely and POST straight to
   the endpoint, so the token must be verified on every request that matters.

2. A token is single-use and short-lived. Cloudflare rejects replays, which
   is what stops a bot harvesting one token and reusing it forever.

3. It fails CLOSED when configured. If Cloudflare cannot be reached the
   submission is refused rather than waved through, because "the verifier is
   down" and "this is a bot" are indistinguishable from here.

Leaving the keys unset disables the whole thing, so local development and
the test suite work without network access or credentials. `check` in this
module makes that impossible to ship: with DEBUG off and no secret key,
Django refuses to start.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.checks import Error, register

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SECONDS = 5

# The field name the Turnstile widget posts under. Fixed by Cloudflare.
TOKEN_FIELD = "cf-turnstile-response"

FAILED = "Could not confirm you are human. Please try again."


def is_enabled():
    return bool(getattr(settings, "TURNSTILE_SECRET_KEY", ""))


def site_key():
    return getattr(settings, "TURNSTILE_SITE_KEY", "")


def _client_ip(request):
    """The visitor's address, as Cloudflare sees it.

    Behind the tunnel every request arrives from the proxy, so REMOTE_ADDR is
    Cloudflare rather than the visitor. CF-Connecting-IP is set by Cloudflare
    itself and is the one to trust here - and only here, because this value
    is handed straight back to Cloudflare, which already knows the true
    address. It is not used for access decisions of our own.
    """
    forwarded = request.META.get("HTTP_CF_CONNECTING_IP")
    if forwarded:
        return forwarded.strip()
    return request.META.get("REMOTE_ADDR", "")


def verify(token, remote_ip=""):
    """Ask Cloudflare whether `token` is a genuine, unused challenge solution.

    Returns True only on an explicit success. Network failures, malformed
    responses and timeouts all return False - see rule 3 above.
    """
    if not token:
        return False

    payload = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    data = urllib.parse.urlencode(payload).encode()
    request = urllib.request.Request(
        VERIFY_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        logger.exception("Turnstile verification could not be completed")
        return False

    # Valid JSON is not necessarily the object we expect - a proxy or error
    # page can return a bare string or list, and .get() on that is an
    # AttributeError that escapes as a 500 on a public form.
    if not isinstance(body, dict):
        logger.warning("Turnstile returned an unexpected payload: %r", body)
        return False

    if body.get("success"):
        return True

    # error-codes is Cloudflare's, not the visitor's - log it, never show it.
    logger.warning(
        "Turnstile rejected a submission: %s", body.get("error-codes", [])
    )
    return False


def _token_from(request):
    """Pull the token out of whichever body format this endpoint uses.

    Branching on content type rather than trying request.POST and falling
    back to request.body: reading request.POST consumes the input stream, and
    Django then raises RawPostDataException on any later access to .body. The
    fallback ordering therefore blew up on exactly the requests it was meant
    to serve - every form-encoded post, which is the contact form and signup.
    """
    content_type = (request.content_type or "").lower()

    if content_type.startswith("application/json"):
        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, TypeError):
            return ""
        return payload.get(TOKEN_FIELD, "") if isinstance(payload, dict) else ""

    return request.POST.get(TOKEN_FIELD, "")


def passed(request):
    """True when this POST carries a valid token, or checks are disabled.

    Usage in a view:

        if not turnstile.passed(request):
            return JsonResponse({"error": turnstile.FAILED}, status=400)
    """
    if not is_enabled():
        return True
    return verify(_token_from(request), _client_ip(request))


def context(request):
    """Template context processor.

    Public templates render the widget only when checks are on, so a
    developer with no keys does not get a permanently broken widget sitting
    in the middle of every form.
    """
    return {
        "turnstile_enabled": is_enabled(),
        "turnstile_site_key": site_key(),
    }


@register()
def check_configured_in_production(app_configs, **kwargs):
    """Refuse to start unprotected outside DEBUG.

    Without this, the single most likely failure mode is deploying with the
    environment variables missing and quietly serving public forms with no
    bot protection at all - which looks exactly like working software.

    settings.TESTING is consulted as well as DEBUG. Django's test runner
    forces DEBUG = False, so "DEBUG is off" alone reads the whole test suite
    as production and this check aborts it before a single test runs.
    """
    if settings.DEBUG or getattr(settings, "TESTING", False) or is_enabled():
        return []
    return [
        Error(
            "Cloudflare Turnstile is not configured but DEBUG is off.",
            hint=(
                "Set TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY from the "
                "Cloudflare dashboard (Turnstile -> your widget). To run "
                "without bot protection on purpose, set DEBUG=true."
            ),
            id="turnstile.E001",
        )
    ]
