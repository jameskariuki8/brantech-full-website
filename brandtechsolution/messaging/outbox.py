"""Building one campaign email, shared by the outbox and the test send so a
test looks exactly like what recipients will get."""

import email.utils
from types import SimpleNamespace

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse

from . import campaigns as campaign_rules
from .placeholders import build_context
from .rendering import html_to_text, render_html, render_text
from .tokens import make_unsubscribe_token

UNSUBSCRIBE_FOOTER = (
    '<hr><p style="font-size:12px;color:#888;">'
    'If you no longer wish to receive these emails, '
    '<a href="{url}">unsubscribe</a>.</p>'
)


def send_campaign_email(campaign, to_email, name="", *, test=False, connection=None):
    """Render and send the campaign to one address. Returns the Message-ID
    it was sent with (no angle brackets), which Mailgun's events carry back.
    Raises whatever the email backend raises."""
    token = make_unsubscribe_token(to_email)
    unsubscribe_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
        "unsubscribe", args=[token]
    )
    context = build_context(SimpleNamespace(name=name, email=to_email), unsubscribe_url)
    subject = render_text(campaign.subject, context)
    if test:
        subject = f"[Test] {subject}"
    html_body = render_html(campaign.body_html, context)
    if unsubscribe_url not in html_body:
        html_body += UNSUBSCRIBE_FOOTER.format(url=unsubscribe_url)
    text_body = html_to_text(html_body)
    if unsubscribe_url not in text_body:
        # html_to_text() drops href attributes, so carry the URL explicitly.
        text_body += (
            "\n\nIf you no longer wish to receive these emails, "
            f"unsubscribe: {unsubscribe_url}"
        )

    message_id = email.utils.make_msgid(domain=settings.MAILBOX_DOMAIN)
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=campaign_rules.from_header(campaign),
        to=[to_email],
        reply_to=campaign_rules.reply_to(campaign),
        connection=connection,
    )
    msg.extra_headers["Message-ID"] = message_id
    msg.extra_headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.extra_headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach_alternative(html_body, "text/html")
    msg.send()
    return message_id.strip("<>")
