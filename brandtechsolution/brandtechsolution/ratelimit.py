"""Per-address rate limiting shared by the public endpoints.

Moved out of brand.views so login, password reset, the chatbot and the
appointment lookups can all count against the same shared cache.
"""
import hashlib

from django.core.cache import cache


def client_ip(request):
    """The visitor's address as seen behind the Cloudflare tunnel.

    Every request reaches the origin from the tunnel, so REMOTE_ADDR is the
    proxy and would put every visitor in one throttle bucket. Both headers are
    checked because the codebase already relies on each: turnstile.py reads
    CF-Connecting-IP, messaging.views reads X-Forwarded-For.

    A client able to reach the origin directly could forge either one, so this
    is only ever used for rate limiting -- never to grant access. Forging it
    buys an attacker nothing that rotating browser_id would not.
    """
    cf = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
    if cf:
        return cf
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def rate_limited(request, bucket, limit, window_seconds, subject=None):
    """True once this client has spent its allowance for `bucket`.

    `subject` counts against something other than the address - an email a
    reset is being sent to, say. It is hashed into the key, since it is
    usually personal data and has no business sitting in Redis in the clear.

    Backed by the shared cache, so the count holds across gunicorn workers
    instead of resetting per process.

    cache.add() only writes when the key is absent, which is what starts the
    window on the first request and lets it expire on its own; incr() then runs
    against a key known to exist. This is deliberately atomic where
    messaging._contact_rate_limited's get/set pair is not -- likes are the
    endpoint someone would actually hammer in parallel.
    """
    if subject is None:
        key = f'ratelimit:{bucket}:{client_ip(request)}'
    else:
        digest = hashlib.sha256(subject.strip().lower().encode()).hexdigest()
        key = f'ratelimit:{bucket}:subject:{digest}'
    cache.add(key, 0, window_seconds)
    try:
        return cache.incr(key) > limit
    except ValueError:
        # The key expired between add() and incr(); treat it as a fresh window.
        return False
