"""Replies the system sends by itself to mail arriving at the webhook.

Today that is one: an application to a job opening that has closed is
answered with a notice that applications are closed, so a late applicant
is not left waiting for a reply that will never come.
"""

import email.utils
import json
import logging

from django.conf import settings
from django.core.cache import cache

from .mailbox import SendError, send_automatic
from .models import MailMessage

logger = logging.getLogger(__name__)

# A ceiling on automatic replies across all senders, so a flood of forged
# applications cannot turn us into a source of bulk mail.
HOURLY_LIMIT = 50
_RATE_KEY = "messaging:autoreply:hour"

# Senders that are machines: answering them starts a loop or bounces.
_MACHINE_LOCALS = ("noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster", "bounce")


def is_automated(sender_email, header):
    """Whether mail from sender_email, with headers read through header(name),
    must not be answered automatically (RFC 3834)."""
    address = (sender_email or "").strip().lower()
    if "@" not in address:
        return True
    local, _, domain = address.rpartition("@")
    if domain == settings.MAILBOX_DOMAIN.lower():
        return True
    if local.startswith(_MACHINE_LOCALS):
        return True
    auto = header("Auto-Submitted").strip().lower()
    if auto and auto != "no":
        return True
    if header("Precedence").strip().lower() in ("bulk", "list", "junk"):
        return True
    return bool(header("List-Id").strip())


def _trace_values(payload, name):
    """Every value of header name in Mailgun's message-headers list.

    Only that list is read: top-level form fields can carry headers the
    sender wrote, and a forger can add their own copy of a verdict header.
    """
    raw = payload.get("message-headers")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    wanted = name.lower()
    return [
        str(pair[1]).strip().lower()
        for pair in (raw if isinstance(raw, list) else [])
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and str(pair[0]).lower() == wanted
    ]


def _domain(address):
    return email.utils.parseaddr(address or "")[1].strip().lower().rpartition("@")[2]


def sender_verified(payload, sender_email):
    """Whether the From address is one Mailgun's SPF check vouches for.

    Anyone can put any address in From, so an unverified automatic reply
    could be aimed at someone who never wrote to us. SPF covers the envelope
    sender, so its domain must also be the From domain. A forger can add a
    passing X-Mailgun-Spf of their own, but cannot remove Mailgun's, so
    every copy must pass.
    """
    verdicts = _trace_values(payload, "X-Mailgun-Spf")
    if not verdicts or any(v != "pass" for v in verdicts):
        return False
    envelope = _domain(str(payload.get("sender") or ""))
    return bool(envelope) and envelope == _domain(sender_email)


def _within_hourly_limit():
    if cache.add(_RATE_KEY, 1, timeout=3600):
        return True
    try:
        count = cache.incr(_RATE_KEY)
    except ValueError:  # expired between add and incr
        cache.set(_RATE_KEY, 1, timeout=3600)
        return True
    return count <= HOURLY_LIMIT


def closed_role_notice(role):
    subject = f"Applications closed: {role.title} ({role.reference})"
    body = (
        f"Hello,\n\n"
        f"Thank you for your interest in the {role.title} role at Teklora.\n\n"
        f"Applications for this role have closed, so we are not able to consider "
        f"your application for it. Please keep an eye on our careers page for new openings:\n"
        f"{settings.SITE_BASE_URL.rstrip('/')}/careers/\n\n"
        f"This is an automatic reply.\n\n"
        f"Teklora Solutions"
    )
    return subject, body


def answer_closed_role(*, subject, recipients, sender_name, sender_email, threads, header, payload):
    """Tell the sender a role is closed when their email applies to one.

    recipients are the addresses the email was delivered to, and threads maps
    each address to the thread it was filed in. header reads a header for the
    checks that only ever stop a reply; payload is the raw webhook body, read
    for the sender verification. Returns the sent MailMessage,
    or None when nothing was sent. Each sender hears this once per role.
    """
    from brand.models import Career

    role = Career.closed_role_for(subject, recipients)
    if role is None:
        return None
    thread = threads.get(role.email.lower())
    if thread is None or thread.spam or is_automated(sender_email, header):
        return None
    if not sender_verified(payload, sender_email):
        logger.info("No applications-closed notice for %s: sender not verified by SPF", role.reference)
        return None
    reply_subject, body = closed_role_notice(role)
    if MailMessage.objects.filter(
        direction="out",
        sent_by__isnull=True,
        subject=reply_subject,
        thread__counterpart_email__iexact=sender_email,
    ).exists():
        return None
    if not _within_hourly_limit():
        logger.warning("Automatic reply limit of %s an hour reached; %s not answered", HOURLY_LIMIT, role.reference)
        return None
    to = email.utils.formataddr((sender_name, sender_email)) if sender_name else sender_email
    try:
        return send_automatic(
            thread, from_address=role.email, to=[to], subject=reply_subject, body=body
        )
    except SendError:
        # The application itself is already filed; only the notice failed.
        logger.exception("Could not send the applications-closed notice for %s to %s", role.reference, sender_email)
        return None
