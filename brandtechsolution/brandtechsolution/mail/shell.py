"""Render and send one themed transactional message.

Three rules, each for a reason the existing code already documents:

- **Inline the CSS.** A system email that renders unstyled in Outlook looks
  broken, which is worse than one that was never themed.
- **Always attach a text alternative.** An alert is the last message that
  should be unreadable in a client that refuses HTML.
- **Do not sanitise.** `nh3` exists in messaging because campaign bodies are
  authored by *users*. These templates are ours, and running them through it
  would strip the table-based layout email clients actually need. Sanitising is
  for untrusted input; this is not that.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from messaging.emailhtml import inline_email_css
from messaging.rendering import html_to_text

logger = logging.getLogger(__name__)


def render_mail(template, context):
    """Return (html, text) for one message.

    The text half is derived rather than written twice, so the two cannot drift
    apart -- a second hand-maintained template is a second thing to forget to
    update.
    """
    html = inline_email_css(render_to_string(template, context))
    return html, html_to_text(html).strip()


def send_mail_html(subject, template, context, recipients, *, fail_silently=False):
    """Send a themed message directly.

    Directly, not through the campaign outbox: the outbox is drained on a Beat
    interval and exists for bulk, while this is transactional and urgent.
    `staff/emails.py:send_invitation` documents the same reasoning, and it
    applies with more force to an alert.

    `fail_silently` defaults to False. The approval workflow passes True, which
    is defensible for a review notice -- the draft is still on the dashboard --
    but not for an alert, where a swallowed send means the failure is silent
    again by a different route.
    """
    if not recipients:
        logger.warning("[mail] %r has no recipients; not sending", subject)
        return 0

    html, text = render_mail(template, context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=list(recipients),
    )
    message.attach_alternative(html, "text/html")
    return message.send(fail_silently=fail_silently)
