import json

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from brand.models import Career
from messaging import autoreply
from messaging.models import MailMessage


@override_settings(MAILBOX_DOMAIN="teklora.co.ke", SITE_BASE_URL="https://teklora.co.ke")
class ClosedRoleAutoReplyTests(TestCase):
    def setUp(self):
        cache.delete(autoreply._RATE_KEY)
        self.addCleanup(cache.delete, autoreply._RATE_KEY)
        self.url = reverse("mailgun_inbound_webhook")
        self.role = Career.objects.create(
            title="Designer", description="x", email="careers@teklora.co.ke",
            status=Career.STATUS_CLOSED,
        )

    def apply(self, sender="Jane Doe <jane@example.com>", subject=None, spf=("Pass",), envelope=None, **extra):
        # Mailgun puts the envelope sender in "sender", the From header in
        # "from", and its own verdicts in message-headers.
        payload = {
            "sender": envelope or sender,
            "from": sender,
            "message-headers": json.dumps([["X-Mailgun-Spf", v] for v in spf]),
            "recipient": "careers@teklora.co.ke",
            "subject": subject or self.role.application_subject,
            "stripped-text": "Please find my CV attached.",
            "timestamp": "1722898000",
            "token": "t",
            "signature": "s",
            **extra,
        }
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        return response

    def notices(self):
        return [m for m in mail.outbox if m.subject.startswith("Applications closed")]

    def test_applicant_to_a_closed_role_is_told_it_closed(self):
        self.apply()
        [notice] = self.notices()
        self.assertEqual(notice.to, ["Jane Doe <jane@example.com>"])
        self.assertIn("careers@teklora.co.ke", notice.from_email)
        self.assertIn("Applications for this role have closed", notice.body)
        self.assertEqual(notice.extra_headers["Auto-Submitted"], "auto-replied")
        # Filed in the same conversation as the application.
        sent = MailMessage.objects.get(direction="out")
        received = MailMessage.objects.get(direction="in")
        self.assertEqual(sent.thread_id, received.thread_id)
        self.assertTrue(sent.thread.unread)

    def test_each_sender_is_told_once(self):
        self.apply()
        self.apply(**{"Message-Id": "<second@example.com>"})
        self.assertEqual(len(self.notices()), 1)

    def test_open_role_gets_no_notice(self):
        self.role.status = Career.STATUS_OPEN
        self.role.save()
        self.apply()
        self.assertEqual(self.notices(), [])

    def test_unrelated_mail_to_careers_gets_no_notice(self):
        self.apply(subject="Speculative application")
        self.assertEqual(self.notices(), [])

    def test_automated_senders_get_no_notice(self):
        self.apply(sender="mailer-daemon@example.com")
        self.apply(sender="bot@example.com", **{"Auto-Submitted": "auto-replied"})
        self.apply(sender="list@example.com", **{"Precedence": "bulk"})
        self.apply(sender="colleague@teklora.co.ke")
        self.assertEqual(self.notices(), [])

    def test_forged_sender_gets_no_notice(self):
        # From can name anyone; only an SPF-verified, aligned sender is answered.
        self.apply(spf=("Fail",))
        self.apply(spf=())
        self.assertEqual(self.notices(), [])

    def test_a_forged_passing_verdict_does_not_count(self):
        # Top-level field and an extra copy in the headers, both written by
        # the sender; Mailgun's own Fail is still in the list.
        self.apply(spf=("Pass", "Fail"), **{"X-Mailgun-Spf": "Pass"})
        self.assertEqual(self.notices(), [])

    def test_spf_pass_for_another_domain_does_not_count(self):
        # SPF passed for the forger's own envelope domain, not for From.
        self.apply(sender="victim@example.org", envelope="bounce@forger.example")
        self.assertEqual(self.notices(), [])

    def test_hourly_limit_caps_notices(self):
        autoreply.HOURLY_LIMIT, original = 2, autoreply.HOURLY_LIMIT
        self.addCleanup(setattr, autoreply, "HOURLY_LIMIT", original)
        for n in range(4):
            self.apply(sender=f"applicant{n}@example.com")
        self.assertEqual(len(self.notices()), 2)
