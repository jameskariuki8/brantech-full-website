"""Mailgun delivery for every outbound email.

Replaces SMTP-to-Gmail. Gmail caps a consumer account at roughly 500
recipients a day and a Workspace account at 2,000, while the outbox is
configured to push OUTBOX_BATCH_SIZE recipients every BEAT_OUTBOX_INTERVAL
seconds -- 3,000 an hour at the defaults. Campaign mail from a Gmail account
also earns throttling and reputation damage regardless of the cap.

This is a Django email backend, not a separate send path, so `send_mail()`,
`EmailMultiAlternatives` and the outbox's `get_connection()` all keep working
untouched. Swapping providers again means changing EMAIL_BACKEND, nothing else.

Two details matter for the outbox specifically:

1. open()/close() hold one requests.Session for the life of the connection.
   The outbox opens a connection once and reuses it across a whole batch to
   avoid a TLS handshake per message; that optimisation only survives if the
   backend actually pools, which a fresh requests.post() per call would not.

2. extra_headers are forwarded as Mailgun's `h:` parameters. The outbox sets
   List-Unsubscribe and List-Unsubscribe-Post, which Gmail and Yahoo require
   from bulk senders -- dropping them silently would hurt deliverability in a
   way that no test would catch.
"""
import logging
import re

import requests
from django.conf import settings
from django.core.checks import Error, register
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.mailgun.net/v3"


def is_configured():
    return bool(
        getattr(settings, "MAILGUN_API_KEY", "")
        and getattr(settings, "MAILGUN_DOMAIN", "")
    )


def messages_url():
    """The endpoint a message is POSTed to.

    MAILGUN_BASE_URL is the API root, not the per-domain path -- EU accounts
    live at https://api.eu.mailgun.net/v3 rather than the default US host, and
    that is the whole reason it is configurable. Appending the domain when it
    is already there is the obvious way to get this wrong, so a base URL that
    already ends in the domain is left alone rather than turned into a 404.
    """
    base = (getattr(settings, "MAILGUN_BASE_URL", "") or DEFAULT_BASE_URL).rstrip("/")
    domain = getattr(settings, "MAILGUN_DOMAIN", "")
    if domain and not base.endswith(f"/{domain}"):
        base = f"{base}/{domain}"
    return f"{base}/messages"


class MailgunEmailBackend(BaseEmailBackend):
    """Send EmailMessage objects through the Mailgun HTTP API."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, "MAILGUN_API_KEY", "")
        self.timeout = getattr(settings, "EMAIL_TIMEOUT", 10) or 10
        self.session = None

    def open(self):
        if self.session is not None:
            return False
        self.session = requests.Session()
        self.session.auth = ("api", self.api_key)
        return True

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        if not is_configured():
            # Refusing here rather than reporting a successful send: a caller
            # that believes mail went out will mark its campaign rows sent.
            logger.error("Mailgun is not configured; refusing to send %s message(s)", len(email_messages))
            if not self.fail_silently:
                raise RuntimeError(
                    "Mailgun is not configured (set MAILGUN_API_KEY and MAILGUN_DOMAIN)."
                )
            return 0

        opened = self.open()
        try:
            return sum(1 for m in email_messages if self._send(m))
        finally:
            # Only tear down a session this call created. The outbox opens the
            # connection itself and expects it to survive the whole batch.
            if opened:
                self.close()

    def _send(self, message):
        recipients = message.recipients()
        if not recipients:
            return False

        data = {
            "from": message.from_email,
            "to": list(message.to),
            "subject": message.subject or "",
        }
        if message.cc:
            data["cc"] = list(message.cc)
        if message.bcc:
            data["bcc"] = list(message.bcc)
        if getattr(message, "reply_to", None):
            data["h:Reply-To"] = ", ".join(message.reply_to)

        # content_subtype is "html" when a caller built a single HTML-only
        # message; otherwise body is the plain-text part.
        if message.content_subtype == "html":
            data["html"] = message.body or ""
        else:
            data["text"] = message.body or ""

        for content, mimetype in getattr(message, "alternatives", []) or []:
            if mimetype == "text/html":
                data["html"] = content

        for name, value in (message.extra_headers or {}).items():
            data[f"h:{name}"] = value

        files = self._attachments(message)
        url = messages_url()

        try:
            response = self.session.post(
                url, data=data, files=files or None, timeout=self.timeout
            )
        except requests.RequestException as exc:
            logger.warning("Mailgun request to %s failed for %s: %s", url, recipients, exc)
            if not self.fail_silently:
                raise
            return False

        if response.status_code >= 400:
            # Mailgun puts the reason in a JSON "message" field; the raw body is
            # the fallback. Either way it must reach the caller, because the
            # outbox records it against the recipient and shows it in the panel.
            detail = response.text[:500]
            try:
                detail = response.json().get("message", detail)
            except ValueError:
                pass
            # The URL belongs in the message. A 404 from Mailgun is almost always
            # a malformed base URL rather than anything about the message, and
            # without the URL there is nothing in the error to act on.
            logger.warning(
                "Mailgun rejected a message to %s at %s (HTTP %s): %s",
                recipients, url, response.status_code, detail,
            )
            if not self.fail_silently:
                raise RuntimeError(
                    f"Mailgun error {response.status_code} from {url}: {detail}"
                )
            return False

        return True

    def _attachments(self, message):
        files = []
        for attachment in getattr(message, "attachments", []) or []:
            if isinstance(attachment, tuple) and len(attachment) == 3:
                filename, content, mimetype = attachment
                files.append(("attachment", (filename, content, mimetype)))
            else:
                # A MIMEBase built by hand. Nothing here produces one, and
                # guessing at its encoding would be worse than saying so.
                logger.warning(
                    "Mailgun backend skipped an unsupported attachment type: %r",
                    type(attachment),
                )
        return files


CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Matches the version segment of an API root: /v3, /v4, ...
_VERSION_SEGMENT = re.compile(r"/v\d+$")


@register()
def check_mailgun_base_url(app_configs, **kwargs):
    """Catch an API root missing its version segment.

    Mailgun's router answers anything outside a versioned path with a plain
    "404 page not found" -- not a JSON API error -- so this misconfiguration
    looks like a problem with the message rather than the URL, and it takes
    out every outbound email at once. Cheaper to refuse at boot.

    A base URL already ending in the sending domain is accepted, because
    messages_url() tolerates that form.
    """
    if not is_configured():
        return []
    base = (getattr(settings, "MAILGUN_BASE_URL", "") or DEFAULT_BASE_URL).rstrip("/")
    domain = getattr(settings, "MAILGUN_DOMAIN", "")
    if _VERSION_SEGMENT.search(base) or (domain and base.endswith(f"/{domain}")):
        return []
    return [
        Error(
            f"MAILGUN_BASE_URL ({base!r}) has no API version segment.",
            hint=(
                "Use the versioned API root, e.g. https://api.mailgun.net/v3 "
                "(or https://api.eu.mailgun.net/v3 for an EU account). Without "
                "it every send fails with a plain-text 404."
            ),
            id="mailgun.E002",
        )
    ]


@register()
def check_email_configured(app_configs, **kwargs):
    """Refuse to start in production with mail pointed at the console.

    settings.py falls back to the console backend when no provider credentials
    are present, which is right for development and catastrophic in production:
    every message is printed to stdout and reported as sent, so a campaign
    marches through its recipients marking them delivered while nobody receives
    anything, and no exception is ever raised.

    Checking the resolved backend rather than the Mailgun keys specifically is
    deliberate -- an SMTP deployment is still a working deployment. What must
    never ship is "mail goes nowhere and says it worked". Same guard, and same
    reasoning, as turnstile.py.
    """
    if settings.DEBUG or settings.EMAIL_BACKEND != CONSOLE_BACKEND:
        return []
    return [
        Error(
            "Email is unconfigured with DEBUG off: messages would be printed "
            "to stdout and reported as sent.",
            hint=(
                "Set MAILGUN_API_KEY and MAILGUN_DOMAIN, or supply "
                "EMAIL_HOST_USER and EMAIL_HOST_PASSWORD for SMTP."
            ),
            id="mailgun.E001",
        )
    ]
