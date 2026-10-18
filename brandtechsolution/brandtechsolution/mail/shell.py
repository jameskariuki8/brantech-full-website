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
from django.core.mail import EmailMultiAlternatives, get_connection
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
    return send_mail_each(
        subject=subject,
        message=text,
        html_message=html,
        recipient_list=recipients,
        fail_silently=fail_silently,
    )


def send_mail_each(subject, message, recipient_list, *, from_email=None,
                   html_message=None, fail_silently=False):
    """send_mail(), but one message per recipient.

    Staff notifications go to the personal addresses of everyone holding a
    capability. Sent as one message, every recipient saw every other
    recipient's address on the To line, so each person now gets their own.

    Every recipient is attempted even when one fails. Returns how many were
    sent; with fail_silently=False the first error is raised afterwards.
    """
    recipients = list(dict.fromkeys(r for r in recipient_list or [] if r))
    if not recipients:
        return 0
    connection = get_connection(fail_silently=fail_silently)
    sent = 0
    first_error = None
    for recipient in recipients:
        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
            connection=connection,
        )
        if html_message:
            email.attach_alternative(html_message, "text/html")
        try:
            sent += email.send(fail_silently=fail_silently)
        except Exception as exc:
            logger.warning("[mail] %r to %s failed: %s", subject, recipient, exc)
            first_error = first_error or exc
    if first_error is not None:
        raise first_error
    return sent
