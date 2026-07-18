from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
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
