from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from messaging.models import Campaign, CampaignRecipient, Suppression
from messaging.rendering import render_body, render_subject, html_to_text
from messaging.tokens import make_unsubscribe_token

UNSUBSCRIBE_FOOTER = (
    '<hr><p style="font-size:12px;color:#888;">'
    'If you no longer wish to receive these emails, '
    '<a href="{url}">unsubscribe</a>.</p>'
)


class Command(BaseCommand):
    help = "Send a batch of pending bulk emails from queued/sending campaigns."

    def handle(self, *args, **options):
        budget = settings.OUTBOX_BATCH_SIZE
        max_attempts = settings.OUTBOX_MAX_ATTEMPTS
        suppressed = set(Suppression.objects.values_list("email", flat=True))

        campaigns = Campaign.objects.filter(status__in=["queued", "sending"])
        connection = get_connection()

        for campaign in campaigns:
            if budget <= 0:
                break

            if campaign.status == "queued":
                campaign.status = "sending"
                if campaign.started_at is None:
                    campaign.started_at = timezone.now()
                campaign.save(update_fields=["status", "started_at"])

            candidate_ids = list(
                campaign.recipients.filter(status="pending")
                .order_by("id")
                .values_list("id", flat=True)[:budget]
            )

            if candidate_ids:
                budget -= len(candidate_ids)

                if suppressed:
                    CampaignRecipient.objects.filter(
                        pk__in=candidate_ids, status="pending", email__in=suppressed
                    ).update(status="skipped")

                # Claim the remaining rows atomically before any mail is sent, so a
                # concurrent run (or a crash mid-batch) cannot re-send them.
                claimed = CampaignRecipient.objects.filter(
                    pk__in=candidate_ids, status="pending"
                ).update(status="sending")

                if claimed:
                    rows = CampaignRecipient.objects.filter(
                        pk__in=candidate_ids, status="sending"
                    ).order_by("id")
                    for recipient in rows:
                        self._send_one(campaign, recipient, connection, max_attempts)

            self._maybe_complete(campaign)

    def _send_one(self, campaign, recipient, connection, max_attempts):
        token = make_unsubscribe_token(recipient.email)
        unsubscribe_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
            "unsubscribe", args=[token]
        )
        subject = render_subject(campaign.subject, recipient.name)
        html_body = render_body(campaign.body_html, recipient.name, unsubscribe_url)
        if unsubscribe_url not in html_body:
            html_body += UNSUBSCRIBE_FOOTER.format(url=unsubscribe_url)
        text_body = html_to_text(html_body)
        if unsubscribe_url not in text_body:
            # html_to_text() drops href attributes, so carry the URL explicitly.
            text_body += (
                "\n\nIf you no longer wish to receive these emails, "
                f"unsubscribe: {unsubscribe_url}"
            )

        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient.email],
                connection=connection,
            )
            msg.extra_headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            msg.attach_alternative(html_body, "text/html")
            msg.send()
        except Exception as exc:  # noqa: BLE001 - record and retry/fail
            recipient.attempts += 1
            recipient.error = str(exc)[:1000]
            if recipient.attempts >= max_attempts:
                recipient.status = "failed"
                Campaign.objects.filter(pk=campaign.pk).update(
                    failed_count=F("failed_count") + 1
                )
            else:
                # Release the claim so a later run retries this recipient.
                recipient.status = "pending"
            recipient.save(update_fields=["attempts", "error", "status"])
            return

        recipient.status = "sent"
        recipient.sent_at = timezone.now()
        recipient.attempts += 1
        recipient.save(update_fields=["status", "sent_at", "attempts"])
        Campaign.objects.filter(pk=campaign.pk).update(sent_count=F("sent_count") + 1)

    def _maybe_complete(self, campaign):
        remaining = campaign.recipients.filter(
            status__in=["pending", "sending"]
        ).count()
        if remaining:
            return
        c = Campaign.objects.get(pk=campaign.pk)
        failed = c.recipients.filter(status="failed").count()
        sent = c.recipients.filter(status="sent").count()
        c.status = "failed" if (sent == 0 and failed > 0) else "sent"
        c.completed_at = timezone.now()
        c.save(update_fields=["status", "completed_at"])
