"""Staff handles: the username a person picks once, which is also the local
part of their work address (<handle>@MAILBOX_DOMAIN).

Invited accounts start with their personal email as the username. Until they
pick a handle they have no mailbox, and the panel sends them to pick one.
"""

import re
import unicodedata

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
MIN_LENGTH = 3
MAX_LENGTH = 30

# Team addresses anyone with view_inbox reads. Reserved so nobody can
# claim one as a personal handle.
SHARED_MAILBOXES = ("info", "hello", "support")

# Names a mail provider, a client or a phishing email could lean on.
RESERVED = frozenset(SHARED_MAILBOXES) | {
    "abuse", "admin", "administrator", "billing", "careers", "contact",
    "hostmaster", "hr", "jobs", "legal", "mail", "mailer-daemon", "marketing",
    "no-reply", "noreply", "office", "postmaster", "press", "privacy",
    "root", "sales", "security", "staff", "system", "team", "teklora",
    "webmaster", "www",
}


def mailbox_address(handle):
    return f"{handle}@{settings.MAILBOX_DOMAIN}"


def needs_handle(user):
    """True for a staff account still signed in under an email address."""
    return bool(user.is_authenticated and user.is_staff and "@" in user.username)


def validate_handle(raw, user=None):
    """Return the handle normalised, or raise ValidationError."""
    handle = (raw or "").strip().lower()
    if not MIN_LENGTH <= len(handle) <= MAX_LENGTH:
        raise ValidationError(
            f"Use between {MIN_LENGTH} and {MAX_LENGTH} characters."
        )
    if not HANDLE_RE.match(handle):
        raise ValidationError(
            "Use lowercase letters, digits, dots and hyphens, "
            "starting and ending with a letter or digit."
        )
    if ".." in handle or "--" in handle or ".-" in handle or "-." in handle:
        raise ValidationError("Dots and hyphens cannot sit next to each other.")
    if handle in RESERVED:
        raise ValidationError("That address is reserved. Pick another.")
    taken = User.objects.filter(username__iexact=handle)
    if user is not None:
        taken = taken.exclude(pk=user.pk)
    if taken.exists():
        raise ValidationError("Someone already has that address.")
    return handle


def _slug(text):
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", ascii_text.lower())


def suggest_handles(user, limit=4):
    """Free, valid handles built from the person's name or email."""
    first, last = _slug(user.first_name), _slug(user.last_name)
    local = user.email.split("@")[0] if user.email else ""
    candidates = []
    if first and last:
        candidates += [f"{first}.{last}", f"{first}{last[0]}", f"{first[0]}.{last}", first]
    elif first:
        candidates.append(first)
    local_slug = re.sub(r"[^a-z0-9.-]+", "", local.lower()).strip(".-")
    local_slug = re.sub(r"[.-]{2,}", ".", local_slug)
    candidates.append(re.sub(r"\d+$", "", local_slug))

    found = []
    for candidate in candidates:
        if candidate in found:
            continue
        try:
            found.append(validate_handle(candidate, user=user))
        except ValidationError:
            continue
        if len(found) == limit:
            break
    return found
