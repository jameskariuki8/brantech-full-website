from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from messaging.models import Campaign, CampaignRecipient, Suppression
from messaging.rendering import render_body, render_subject, html_to_text
from messaging.tokens import make_unsubscribe_token


class Command(BaseCommand):
    help = "Send a batch of pending bulk emails from queued/sending campaigns."

    def handle(self, *args, **options):
        batch_size = settings.OUTBOX_BATCH_SIZE
        max_attempts = settings.OUTBOX_MAX_ATTEMPTS
        suppressed = set(Suppression.objects.values_list("email", flat=True))

        campaigns = Campaign.objects.filter(status__in=["queued", "sending"])
        connection = get_connection()

        for campaign in campaigns:
            if campaign.status == "queued":
                campaign.status = "sending"
                if campaign.started_at is None:
                    campaign.started_at = timezone.now()
                campaign.save(update_fields=["status", "started_at"])

            pending = list(
                campaign.recipients.filter(status="pending").order_by("id")[:batch_size]
            )

            for recipient in pending:
                if recipient.email in suppressed:
                    recipient.status = "skipped"
                    recipient.save(update_fields=["status"])
                    continue
                self._send_one(campaign, recipient, connection, max_attempts)

            self._maybe_complete(campaign)

    def _send_one(self, campaign, recipient, connection, max_attempts):
        token = make_unsubscribe_token(recipient.email)
        unsubscribe_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
            "unsubscribe", args=[token]
        )
        subject = render_subject(campaign.subject, recipient.name)
        html_body = render_body(campaign.body_html, recipient.name, unsubscribe_url)
        text_body = html_to_text(html_body)

        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient.email],
                connection=connection,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send()
        except Exception as exc:  # noqa: BLE001 - record and retry/fail
            recipient.attempts += 1
            recipient.error = str(exc)[:1000]
            if recipient.attempts >= max_attempts:
                recipient.status = "failed"
                recipient.save(update_fields=["attempts", "error", "status"])
                Campaign.objects.filter(pk=campaign.pk).update(
                    failed_count=campaign.__class__.objects.get(pk=campaign.pk).failed_count + 1
                )
            else:
                recipient.save(update_fields=["attempts", "error"])
            return

        recipient.status = "sent"
        recipient.sent_at = timezone.now()
        recipient.attempts += 1
        recipient.save(update_fields=["status", "sent_at", "attempts"])
        with transaction.atomic():
            c = Campaign.objects.select_for_update().get(pk=campaign.pk)
            c.sent_count += 1
            c.save(update_fields=["sent_count"])

    def _maybe_complete(self, campaign):
        remaining = campaign.recipients.filter(status="pending").count()
        if remaining:
            return
        c = Campaign.objects.get(pk=campaign.pk)
        failed = c.recipients.filter(status="failed").count()
        sent = c.recipients.filter(status="sent").count()
        c.status = "failed" if (sent == 0 and failed > 0) else "sent"
        c.completed_at = timezone.now()
        c.save(update_fields=["status", "completed_at"])
