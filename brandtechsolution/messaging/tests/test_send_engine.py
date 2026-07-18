import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.db.models.query import QuerySet
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from messaging.models import Campaign, CampaignRecipient, Suppression


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="admin@example.com",
    OUTBOX_BATCH_SIZE=50,
    OUTBOX_MAX_ATTEMPTS=3,
)
class SendEngineTests(TestCase):
    def _campaign(self, status="queued"):
        c = Campaign.objects.create(
            name="C", subject="Hi {{ name }}", body_html="<p>Hi {{ name }}</p>",
            status=status, total=0,
        )
        return c

    def test_sends_pending_and_marks_sent(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com", name="Ada")
        c.total = 1
        c.save(update_fields=["total"])
        call_command("process_email_outbox")
        r = CampaignRecipient.objects.get(campaign=c)
        c.refresh_from_db()
        self.assertEqual(r.status, "sent")
        self.assertEqual(c.status, "sent")
        self.assertEqual(c.sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Ada", mail.outbox[0].subject)

    def test_skips_suppressed(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com")
        c.total = 1
        c.save(update_fields=["total"])
        Suppression.objects.create(email="a@x.com")
        call_command("process_email_outbox")
        r = CampaignRecipient.objects.get(campaign=c)
        self.assertEqual(r.status, "skipped")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(OUTBOX_BATCH_SIZE=1)
    def test_batch_size_limits_per_run(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com")
        CampaignRecipient.objects.create(campaign=c, email="b@x.com")
        c.total = 2
        c.save(update_fields=["total"])
        call_command("process_email_outbox")
        sent = CampaignRecipient.objects.filter(campaign=c, status="sent").count()
        self.assertEqual(sent, 1)
        c.refresh_from_db()
        self.assertEqual(c.status, "sending")  # not done yet

    def test_running_twice_does_not_resend(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com", name="Ada")
        c.total = 1
        c.save(update_fields=["total"])
        call_command("process_email_outbox")
        call_command("process_email_outbox")
        r = CampaignRecipient.objects.get(campaign=c)
        c.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(r.status, "sent")
        self.assertEqual(c.sent_count, 1)

    def test_unsubscribe_link_always_present(self):
        c = Campaign.objects.create(
            name="C", subject="Hi", body_html="<p>No placeholder here</p>",
            status="queued", total=1,
        )
        CampaignRecipient.objects.create(campaign=c, email="a@x.com")
        call_command("process_email_outbox")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        html = msg.alternatives[0][0]
        self.assertIn("/unsubscribe/", html)
        self.assertIn("/unsubscribe/", msg.body)
        self.assertIn("List-Unsubscribe", msg.extra_headers)
        self.assertIn("/unsubscribe/", msg.extra_headers["List-Unsubscribe"])

    @override_settings(OUTBOX_BATCH_SIZE=1)
    def test_batch_budget_is_per_run_across_campaigns(self):
        for addr in ("a@x.com", "b@x.com"):
            c = self._campaign()
            c.total = 1
            c.save(update_fields=["total"])
            CampaignRecipient.objects.create(campaign=c, email=addr)
        call_command("process_email_outbox")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(CampaignRecipient.objects.filter(status="sent").count(), 1)

    def test_failed_count_increments_on_failure(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com")
        c.total = 1
        c.save(update_fields=["total"])
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="127.0.0.1", EMAIL_PORT=1,
        ):
            for _ in range(3):
                call_command("process_email_outbox")
        r = CampaignRecipient.objects.get(campaign=c)
        c.refresh_from_db()
        self.assertEqual(r.status, "failed")
        self.assertEqual(c.failed_count, 1)

    def test_skips_rows_already_claimed_by_another_run(self):
        """A row another run claimed before this run started is not sent."""
        c = self._campaign()
        mine = CampaignRecipient.objects.create(campaign=c, email="mine@x.com")
        CampaignRecipient.objects.create(
            campaign=c, email="theirs@x.com", status="sending",
            claim_token=uuid.uuid4(), claimed_at=timezone.now(),
        )
        c.total = 2
        c.save(update_fields=["total"])

        call_command("process_email_outbox")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [mine.email])

    def test_sends_only_rows_this_run_actually_claimed(self):
        """A row stolen between our SELECT and our UPDATE must not be sent.

        Both recipients are pending when this run picks its candidates, so both
        land in candidate_ids. A concurrent run then claims one of them just
        before our claim UPDATE lands. Only the row we actually won may be sent
        -- filtering candidates by status="sending" alone would send both.
        """
        c = self._campaign()
        mine = CampaignRecipient.objects.create(campaign=c, email="mine@x.com")
        theirs = CampaignRecipient.objects.create(campaign=c, email="theirs@x.com")
        c.total = 2
        c.save(update_fields=["total"])

        real_update = QuerySet.update
        stolen = []

        def steal_then_update(self, **kwargs):
            if kwargs.get("status") == "sending" and not stolen:
                stolen.append(True)
                real_update(
                    CampaignRecipient.objects.filter(pk=theirs.pk),
                    status="sending", claim_token=uuid.uuid4(),
                    claimed_at=timezone.now(),
                )
            return real_update(self, **kwargs)

        with patch.object(QuerySet, "update", steal_then_update):
            call_command("process_email_outbox")

        self.assertTrue(stolen, "concurrent claim never fired -- test is not exercising the race")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [mine.email])
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, "sending")  # left for the run that won it

    @override_settings(OUTBOX_STALE_CLAIM_MINUTES=15)
    def test_reaper_releases_stale_claims(self):
        """A claim abandoned by a crashed run is released and retried."""
        c = self._campaign()
        r = CampaignRecipient.objects.create(
            campaign=c, email="stale@x.com", status="sending",
            claim_token=uuid.uuid4(),
            claimed_at=timezone.now() - timedelta(hours=2),
        )
        c.total = 1
        c.save(update_fields=["total"])

        call_command("process_email_outbox")

        r.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(r.status, "sent")
        self.assertEqual(c.status, "sent")  # campaign no longer stalls forever

    @override_settings(OUTBOX_STALE_CLAIM_MINUTES=15)
    def test_reaper_leaves_fresh_claims_alone(self):
        """A claim held by a live concurrent run must survive the reaper."""
        c = self._campaign()
        token = uuid.uuid4()
        r = CampaignRecipient.objects.create(
            campaign=c, email="fresh@x.com", status="sending",
            claim_token=token, claimed_at=timezone.now() - timedelta(minutes=1),
        )
        c.total = 1
        c.save(update_fields=["total"])

        call_command("process_email_outbox")

        r.refresh_from_db()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(r.status, "sending")
        self.assertEqual(r.claim_token, token)

    def test_failed_send_retries_then_fails(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com")
        c.total = 1
        c.save(update_fields=["total"])
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="127.0.0.1", EMAIL_PORT=1,  # unreachable → send raises
        ):
            for _ in range(3):
                call_command("process_email_outbox")
        r = CampaignRecipient.objects.get(campaign=c)
        c.refresh_from_db()
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.attempts, 3)
        self.assertEqual(c.status, "failed")
