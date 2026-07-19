import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from messaging.models import Campaign, CampaignRecipient, Suppression
from messaging.placeholders import build_context
from messaging.rendering import html_to_text, render_html, render_text
from messaging.tokens import make_unsubscribe_token

logger = logging.getLogger(__name__)

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

        self._release_stale_claims()

        suppressed = set(Suppression.objects.values_list("email", flat=True))

        campaigns = Campaign.objects.filter(status__in=["queued", "sending"])
        connection = get_connection()

        # Open once for the whole run: every message otherwise pays a full TLS
        # handshake, which is what the throttling design exists to avoid. A
        # failure here must not abort the run -- each send then raises on its
        # own and is recorded against its recipient's attempt count as usual.
        try:
            connection.open()
        except Exception as exc:  # noqa: BLE001 - per-recipient handling covers this
            logger.warning("Outbox: SMTP connection open failed: %s", exc)

        try:
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
                    if suppressed:
                        CampaignRecipient.objects.filter(
                            pk__in=candidate_ids, status="pending", email__in=suppressed
                        ).update(status="skipped")

                    # Claim the remaining rows atomically before any mail is sent,
                    # stamping our own token so we can tell which rows *this* run
                    # won. A concurrent run may have claimed some of our candidates
                    # between the SELECT above and this UPDATE; those rows are
                    # theirs to send, not ours.
                    token = uuid.uuid4()
                    claimed = CampaignRecipient.objects.filter(
                        pk__in=candidate_ids, status="pending"
                    ).update(
                        status="sending", claim_token=token, claimed_at=timezone.now()
                    )
                    # Budget reflects real send volume: rows filtered out as
                    # suppressed (or stolen by a concurrent run) above never
                    # reach "sending" and must not eat into this run's budget.
                    budget -= claimed

                    paused = False
                    if claimed:
                        # Filter by token only -- never by status="sending" alone.
                        rows = CampaignRecipient.objects.filter(
                            claim_token=token
                        ).order_by("id")
                        for recipient in rows:
                            # Re-check live status before every send: an operator
                            # may have paused this campaign mid-run. Without this,
                            # a paused campaign keeps sending its already-claimed
                            # batch to completion.
                            current_status = (
                                Campaign.objects.filter(pk=campaign.pk)
                                .values_list("status", flat=True)
                                .first()
                            )
                            if current_status != "sending":
                                paused = True
                                break
                            self._send_one(
                                campaign, recipient, connection, max_attempts
                            )

                        if paused:
                            # Release the rest of this run's claim -- unsent rows
                            # must not be stranded in "sending"; they go back to
                            # "pending" so a resume picks them up again.
                            CampaignRecipient.objects.filter(
                                claim_token=token, status="sending"
                            ).update(status="pending", claim_token=None, claimed_at=None)

                    if paused:
                        continue

                self._maybe_complete(campaign)
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - nothing useful to do on teardown
                pass

    def _release_stale_claims(self):
        """Return rows abandoned mid-send (crash, deploy) to the pending pool.

        Without this a row stuck in "sending" is never re-selected, and the
        campaign never completes because _maybe_complete() counts it as
        outstanding forever.
        """
        stale_before = timezone.now() - timedelta(
            minutes=settings.OUTBOX_STALE_CLAIM_MINUTES
        )
        CampaignRecipient.objects.filter(
            status="sending", claimed_at__lt=stale_before
        ).update(status="pending", claim_token=None, claimed_at=None)

    def _send_one(self, campaign, recipient, connection, max_attempts):
        token = make_unsubscribe_token(recipient.email)
        unsubscribe_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
            "unsubscribe", args=[token]
        )
        context = build_context(recipient, unsubscribe_url)
        subject = render_text(campaign.subject, context)
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

        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient.email],
                connection=connection,
            )
            msg.extra_headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            msg.extra_headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            msg.attach_alternative(html_body, "text/html")
            msg.send()
        except Exception as exc:  # noqa: BLE001 - record and retry/fail
            recipient.attempts += 1
            logger.warning(
                "Outbox: send failed for recipient %s (attempt %s): %s",
                recipient.pk, recipient.attempts, exc,
            )
            recipient.error = str(exc)[:1000]
            if recipient.attempts >= max_attempts:
                recipient.status = "failed"
                Campaign.objects.filter(pk=campaign.pk).update(
                    failed_count=F("failed_count") + 1
                )
            else:
                # Release the claim so a later run retries this recipient.
                recipient.status = "pending"
            # Terminal or released: the claim is over either way, so drop the
            # token instead of leaving it to linger on a settled row.
            recipient.claim_token = None
            recipient.claimed_at = None
            recipient.save(
                update_fields=[
                    "attempts", "error", "status", "claim_token", "claimed_at",
                ]
            )
            return

        recipient.status = "sent"
        recipient.sent_at = timezone.now()
        recipient.attempts += 1
        recipient.claim_token = None
        recipient.claimed_at = None
        recipient.save(
            update_fields=[
                "status", "sent_at", "attempts", "claim_token", "claimed_at",
            ]
        )
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
        if c.status == "failed":
            logger.error(
                "Outbox: campaign %s finished with 0 sent, %s failed",
                campaign.pk, failed,
            )
        c.completed_at = timezone.now()
        c.save(update_fields=["status", "completed_at"])
