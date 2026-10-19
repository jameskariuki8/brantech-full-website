"""Failed-login accounting for /login/.

Checking a password is deliberately slow (PBKDF2), and the site runs three
gunicorn workers, so a bot posting guesses at /login/ does not just guess - it
queues every real sign-in behind its hashing. The defence is to refuse bots
BEFORE a password is ever hashed, without handing the attacker a way to lock
real people out.

Three counters of failed attempts, all over the same window:

- per address: past ADDRESS_CHALLENGE failures the address must pass the
  Turnstile challenge on each attempt; past ADDRESS_BLOCK it is refused
  outright until the window ends. Mobile carriers put many people behind one
  address, so the hard block sits far above anything a person would reach.
- per account: past ACCOUNT_CHALLENGE failures, anyone signing in to that
  account must pass the challenge. Never a lockout - that would let anyone
  shut a colleague out by typing their email wrong ten times. The real owner
  solves the challenge and gets in.
- site-wide: past SITE_CHALLENGE failures, everyone gets the challenge. This
  covers a botnet spreading guesses across many addresses and accounts, each
  staying under its own limit.

A request without a valid challenge token is turned away before the database
or the hasher is touched, so a flood costs the bot far more than it costs us.
With Turnstile unconfigured (local development) the challenge always passes
and only the per-address block applies.

Counts live in the shared cache so they hold across workers. Account keys are
hashed: the identifier is personal data and has no business sitting in Redis
in the clear.
"""
import hashlib

from django.core.cache import cache

WINDOW_SECONDS = 15 * 60

ADDRESS_CHALLENGE = 5
ADDRESS_BLOCK = 30
ACCOUNT_CHALLENGE = 5
SITE_CHALLENGE = 100


def _address_key(ip):
    return f'login-fail:ip:{ip}'


def _account_key(identifier):
    digest = hashlib.sha256(identifier.strip().lower().encode()).hexdigest()
    return f'login-fail:account:{digest}'


SITE_KEY = 'login-fail:site'


def _count(key):
    return cache.get(key, 0)


def _bump(key):
    # Same add-then-incr pattern as views._rate_limited: add() starts the
    # window only when the key is absent, so it expires on its own.
    cache.add(key, 0, WINDOW_SECONDS)
    try:
        cache.incr(key)
    except ValueError:
        # Expired between add() and incr(); start a fresh window.
        cache.add(key, 1, WINDOW_SECONDS)


def blocked(ip):
    """True when this address has failed too often to try again yet."""
    return _count(_address_key(ip)) >= ADDRESS_BLOCK


def needs_challenge(ip, identifier=None):
    """True when the next attempt must carry a Turnstile token."""
    if _count(_address_key(ip)) >= ADDRESS_CHALLENGE:
        return True
    if _count(SITE_KEY) >= SITE_CHALLENGE:
        return True
    return bool(identifier) and _count(_account_key(identifier)) >= ACCOUNT_CHALLENGE


def record_failure(ip, identifier):
    _bump(_address_key(ip))
    _bump(_account_key(identifier))
    _bump(SITE_KEY)


def record_success(identifier):
    """The owner got in, so stop challenging sign-ins to their account.

    The address count is left alone: an attacker who owns one account could
    otherwise sign in to it between guesses and reset their own limit.
    """
    cache.delete(_account_key(identifier))
