"""Single source of truth for email merge placeholders.

The renderer, the admin-panel insert menu, and the preview endpoint all read
from this registry so they cannot drift apart.
"""
import re

from django.utils import timezone

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

PLACEHOLDERS = [
    {
        "key": "name",
        "label": "Full name",
        "description": "Recipient's full name. May be blank for imported addresses.",
        "sample": "Ada Lovelace",
    },
    {
        "key": "first_name",
        "label": "First name",
        "description": "First word of the recipient's name.",
        "sample": "Ada",
    },
    {
        "key": "email",
        "label": "Email address",
        "description": "Recipient's email address.",
        "sample": "ada@example.com",
    },
    {
        "key": "date",
        "label": "Send date",
        "description": "Date the email is sent, e.g. July 19, 2026.",
        "sample": "July 19, 2026",
    },
    {
        "key": "year",
        "label": "Year",
        "description": "Year the email is sent.",
        "sample": "2026",
    },
    {
        "key": "unsubscribe_url",
        "label": "Unsubscribe link",
        "description": "Per-recipient unsubscribe URL. Added automatically if you omit it.",
        "sample": "https://example.com/unsubscribe/sample-token/",
    },
]

PLACEHOLDER_KEYS = {entry["key"] for entry in PLACEHOLDERS}


def build_context(recipient, unsubscribe_url, now=None, extra=None):
    """Resolve placeholder values for one recipient.

    `now` is injectable so date-dependent tests are deterministic.
    `extra` lets future per-recipient fields join without a renderer change.
    """
    now = now or timezone.localtime()
    name = (recipient.name or "").strip()
    context = {
        "name": name,
        "first_name": name.split()[0] if name else "",
        "email": recipient.email or "",
        "date": now.strftime("%B %d, %Y"),
        "year": str(now.year),
        "unsubscribe_url": unsubscribe_url or "",
    }
    if extra:
        context.update(
            {key: ("" if value is None else str(value)) for key, value in extra.items()}
        )
    return context


def sample_context():
    """Placeholder values used to render the editor preview."""
    return {entry["key"]: entry["sample"] for entry in PLACEHOLDERS}


def find_placeholders(text):
    """Every placeholder key appearing in `text`, in order, including duplicates."""
    return PLACEHOLDER_RE.findall(text or "")


def unknown_placeholders(text):
    """Placeholder keys in `text` that the registry does not define, de-duplicated."""
    unknown = []
    for key in find_placeholders(text):
        if key not in PLACEHOLDER_KEYS and key not in unknown:
            unknown.append(key)
    return unknown
