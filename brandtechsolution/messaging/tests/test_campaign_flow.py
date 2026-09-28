"""Templates hold the email; campaigns choose audience, sender and time."""

import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from messaging.models import (
    BlockedSender, Campaign, CampaignRecipient, EmailTemplate, Inquiry, MailSettings, Suppression,
)
from messaging.tests import grant_all_capabilities

LOCMEM = dict(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    MAILBOX_DOMAIN="teklora.co.ke",
    OUTBOX_BATCH_SIZE=50,
    OUTBOX_MAX_ATTEMPTS=3,
)


@override_settings(**LOCMEM)
class CampaignFlowTests(TestCase):
    def setUp(self):
        self.user = grant_all_capabilities(User.objects.create_user(
            "ada", password="p", is_staff=True, first_name="Ada", last_name="Lovelace",
        ))
        self.client.force_login(self.user)
        self.template = EmailTemplate.objects.create(
            name="Launch", subject="Hello {{ first_name }}",
            body_source="<p>Hi {{ name }}</p>", body_html="<p>Hi {{ name }}</p>",
        )

    def _create(self, **extra):
        data = {"name": "Q3 launch", "template": self.template.pk, **extra}
        resp = self.client.post("/api/messaging/campaigns/", data=data)
        self.assertEqual(resp.status_code, 201, resp.content)
        return Campaign.objects.get(pk=resp.json()["id"])

    def _with_recipients(self, campaign, n):
        for i in range(n):
            CampaignRecipient.objects.create(campaign=campaign, email=f"p{i}@example.com")
        campaign.total = n
        campaign.save(update_fields=["total"])

    def _post(self, url, data=None):
        return self.client.post(url, data=json.dumps(data or {}), content_type="application/json")

    def test_campaign_takes_its_content_from_the_template(self):
        c = self._create()
        self.assertEqual(c.subject, "Hello {{ first_name }}")
        self.assertIn("Hi {{ name }}", c.body_html)
        self.assertEqual(c.from_mailbox, "hello")

    def test_editing_a_template_updates_drafts_but_not_queued_campaigns(self):
        draft = self._create()
        queued = self._create(name="Other")
        Campaign.objects.filter(pk=queued.pk).update(status="queued")
        resp = self.client.patch(
            f"/api/messaging/templates/{self.template.pk}/",
            data=json.dumps({"subject": "New subject"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        draft.refresh_from_db()
        queued.refresh_from_db()
        self.assertEqual(draft.subject, "New subject")
        self.assertEqual(queued.subject, "Hello {{ first_name }}")

    def test_sender_must_be_shared_or_own_address(self):
        User.objects.create_user("grace", is_staff=True)
        resp = self.client.post("/api/messaging/campaigns/", data={
            "name": "x", "template": self.template.pk, "from_mailbox": "grace",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._create(from_mailbox="ada").from_mailbox, "ada")

    def test_sent_email_uses_sender_reply_to_and_records_message_id(self):
        c = self._create(from_mailbox="info")
        self._with_recipients(c, 1)
        self.assertEqual(self._post(f"/api/messaging/campaigns/{c.pk}/queue/").status_code, 200)
        call_command("process_email_outbox")
        msg = mail.outbox[0]
        self.assertIn("info@teklora.co.ke", msg.from_email)
        self.assertEqual(msg.reply_to, ["info@teklora.co.ke"])
        recipient = CampaignRecipient.objects.get(campaign=c)
        self.assertTrue(recipient.message_id)
        self.assertEqual(msg.extra_headers["Message-ID"].strip("<>"), recipient.message_id)

    def test_scheduled_campaign_waits_for_its_time(self):
        c = self._create()
        self._with_recipients(c, 1)
        later = (timezone.now() + timedelta(hours=2)).isoformat()
        self.assertEqual(self._post(f"/api/messaging/campaigns/{c.pk}/queue/", {"send_at": later}).status_code, 200)
        call_command("process_email_outbox")
        self.assertEqual(len(mail.outbox), 0)
        Campaign.objects.filter(pk=c.pk).update(send_at=timezone.now() - timedelta(minutes=1))
        call_command("process_email_outbox")
        self.assertEqual(len(mail.outbox), 1)

    def test_unqueue_returns_an_unstarted_campaign_to_draft(self):
        c = self._create()
        self._with_recipients(c, 1)
        self._post(f"/api/messaging/campaigns/{c.pk}/queue/")
        self.assertEqual(self._post(f"/api/messaging/campaigns/{c.pk}/unqueue/").status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, "draft")

    def test_queue_refused_when_audience_exceeds_month_headroom(self):
        MailSettings.objects.update_or_create(pk=1, defaults={"monthly_cap": 3})
        c = self._create()
        self._with_recipients(c, 4)
        resp = self._post(f"/api/messaging/campaigns/{c.pk}/queue/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("only 3 are left", resp.json()["detail"])

    def test_outbox_pauses_campaigns_at_the_cap(self):
        MailSettings.objects.update_or_create(pk=1, defaults={"monthly_cap": 2})
        c = self._create()
        self._with_recipients(c, 3)
        Campaign.objects.filter(pk=c.pk).update(status="queued")
        call_command("process_email_outbox")
        self.assertEqual(len(mail.outbox), 2)
        call_command("process_email_outbox")
        c.refresh_from_db()
        self.assertEqual(c.status, "paused")
        self.assertIn("monthly cap", c.note)
        self.assertEqual(len(mail.outbox), 2)

    def test_only_drafts_can_be_deleted(self):
        c = self._create()
        Campaign.objects.filter(pk=c.pk).update(status="sent")
        self.assertEqual(self.client.delete(f"/api/messaging/campaigns/{c.pk}/").status_code, 400)
        d = self._create(name="d")
        self.assertEqual(self.client.delete(f"/api/messaging/campaigns/{d.pk}/").status_code, 204)

    def test_test_send_goes_to_own_address_marked_test(self):
        c = self._create()
        resp = self._post(f"/api/messaging/campaigns/{c.pk}/test/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mail.outbox[0].to, ["ada@teklora.co.ke"])
        self.assertTrue(mail.outbox[0].subject.startswith("[Test] Hello Ada"))

    def test_overview_lists_senders_and_month(self):
        data = self.client.get("/api/messaging/campaigns/overview/").json()
        values = [s["value"] for s in data["senders"]]
        self.assertEqual(values, ["info", "hello", "support", "ada"])
        self.assertIn("headroom", data["month"])

    def test_audience_skips_staff_blocked_and_own_domain(self):
        User.objects.create_user("cust", email="cust@example.com")
        User.objects.create_user("st", email="st@example.com", is_staff=True)
        Inquiry.objects.create(name="Spam", email="spam@bad.com", message="m")
        Inquiry.objects.create(name="Us", email="info@teklora.co.ke", message="m")
        BlockedSender.objects.create(email="spam@bad.com")
        c = self._create()
        resp = self._post(f"/api/messaging/campaigns/{c.pk}/build_recipients/", {"sources": ["users", "inquiries"]})
        self.assertEqual(resp.status_code, 200)
        emails = set(c.recipients.values_list("email", flat=True))
        self.assertEqual(emails, {"cust@example.com"})


@override_settings(**LOCMEM)
class EventsWebhookTests(TestCase):
    def setUp(self):
        campaign = Campaign.objects.create(name="c", subject="s", body_html="<p>x</p>", status="sent")
        self.row = CampaignRecipient.objects.create(
            campaign=campaign, email="gone@example.com", status="sent",
            sent_at=timezone.now(), message_id="abc@teklora.co.ke",
        )

    def _event(self, **event):
        body = {"signature": {}, "event-data": {"recipient": "gone@example.com", **event}}
        return self.client.post("/messaging/events-webhook/", data=json.dumps(body), content_type="application/json")

    def test_permanent_failure_suppresses_and_marks_bounced(self):
        resp = self._event(event="failed", severity="permanent",
                           message={"headers": {"message-id": "<abc@teklora.co.ke>"}},
                           **{"delivery-status": {"description": "No such user"}})
        self.assertEqual(resp.json()["matched"], 1)
        self.row.refresh_from_db()
        self.assertEqual(self.row.outcome, "bounced")
        self.assertEqual(self.row.outcome_detail, "No such user")
        self.assertEqual(Suppression.objects.get(email="gone@example.com").reason, "bounced")

    def test_temporary_failure_is_ignored(self):
        self._event(event="failed", severity="temporary")
        self.assertFalse(Suppression.objects.exists())

    def test_complaint_suppresses(self):
        self._event(event="complained")
        self.row.refresh_from_db()
        self.assertEqual(self.row.outcome, "complained")
        self.assertEqual(Suppression.objects.get().reason, "complained")

    def test_delivered_never_overwrites_a_bounce(self):
        self._event(event="failed", severity="permanent")
        self._event(event="delivered")
        self.row.refresh_from_db()
        self.assertEqual(self.row.outcome, "bounced")
