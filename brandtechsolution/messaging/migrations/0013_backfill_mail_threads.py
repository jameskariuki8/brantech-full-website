"""File the mail received before mailboxes existed into them.

InboundEmail rows are routed by recipient, as the webhook now does; contact
form inquiries go to the shared info@ mailbox. Inquiries the webhook itself
created from an email are skipped: that email is already an InboundEmail.
"""

import email.utils
import re

from django.conf import settings
from django.db import migrations

SHARED = ("info", "hello", "support")


def _snippet(text):
    return re.sub(r"\s+", " ", text or "").strip()[:180]


def forwards(apps, schema_editor):
    User = apps.get_model("auth", "User")
    InboundEmail = apps.get_model("messaging", "InboundEmail")
    Inquiry = apps.get_model("messaging", "Inquiry")
    MailThread = apps.get_model("messaging", "MailThread")
    MailMessage = apps.get_model("messaging", "MailMessage")
    suffix = "@" + settings.MAILBOX_DOMAIN.lower()

    def file(mailbox, owner, delivered_to, when, name, sender, subject, body, html,
             to, unread, archived):
        thread = MailThread.objects.create(
            mailbox=mailbox, owner=owner, subject=subject[:500],
            counterpart_name=name[:200], counterpart_email=sender,
            snippet=_snippet(body), unread=unread, archived=archived,
            last_message_at=when,
        )
        message = MailMessage.objects.create(
            thread=thread, direction="in", from_name=name[:200], from_email=sender,
            to=to, cc=[], delivered_to=delivered_to, subject=subject[:500],
            body_text=body, body_html=html, status="received",
        )
        MailMessage.objects.filter(pk=message.pk).update(created_at=when)

    for inbound in InboundEmail.objects.all().order_by("received_at"):
        name, _ = email.utils.parseaddr(inbound.message_headers.get("raw_sender", ""))
        addresses = [
            a.lower() for _n, a in email.utils.getaddresses([inbound.recipient])
            if a.lower().endswith(suffix)
        ]
        for address in dict.fromkeys(addresses):
            local = address[: -len(suffix)].split("+", 1)[0]
            owner = User.objects.filter(username__iexact=local, is_staff=True).first()
            if owner is not None:
                mailbox = owner.username
            else:
                mailbox = local if local in SHARED else "other"
            file(mailbox, owner, address, inbound.received_at, name, inbound.sender,
                 inbound.subject, inbound.body_plain, inbound.body_html,
                 [inbound.recipient], inbound.status == "received",
                 inbound.status == "archived")

    for inquiry in Inquiry.objects.exclude(message__startswith="[Inbound Mailgun Email").order_by("created_at"):
        body = inquiry.message
        if inquiry.phone:
            body = f"{body}\n\nPhone / WhatsApp: {inquiry.phone}"
        file("info", None, "info" + suffix, inquiry.created_at, inquiry.name,
             inquiry.email, "Website contact form", body, "", [],
             inquiry.status == "new", inquiry.status == "archived")


def backwards(apps, schema_editor):
    apps.get_model("messaging", "MailThread").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0012_mail_threads"),
        ("auth", "__first__"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
