from django.contrib.auth.models import User
from django.test import TestCase
from messaging.models import Campaign, CampaignRecipient, Inquiry
from messaging.tests import grant_all_capabilities


class CampaignApiTests(TestCase):
    def setUp(self):
        self.staff = grant_all_capabilities(
            User.objects.create_user("staff", password="p", is_staff=True)
        )
        self.client.force_login(self.staff)
        Inquiry.objects.create(name="Ada", email="ada@x.com", message="m")

    def _make_campaign(self):
        resp = self.client.post("/api/messaging/campaigns/", data={
            "name": "Launch", "subject": "Hello", "body_source": "<p>Hi {{ name }}</p>",
        })
        self.assertEqual(resp.status_code, 201)
        return resp.json()["id"]

    def test_create_campaign_is_draft(self):
        cid = self._make_campaign()
        self.assertEqual(Campaign.objects.get(id=cid).status, "draft")

    def test_build_recipients_action(self):
        cid = self._make_campaign()
        resp = self.client.post(
            f"/api/messaging/campaigns/{cid}/build_recipients/",
            data={"sources": ["inquiries"], "manual_emails": ["new@x.com"]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)
        self.assertEqual(CampaignRecipient.objects.filter(campaign_id=cid).count(), 2)

    def test_queue_requires_recipients(self):
        cid = self._make_campaign()
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/queue/")
        self.assertEqual(resp.status_code, 400)

    def test_queue_sets_status(self):
        cid = self._make_campaign()
        self.client.post(
            f"/api/messaging/campaigns/{cid}/build_recipients/",
            data={"sources": ["inquiries"], "manual_emails": []},
            content_type="application/json",
        )
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/queue/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Campaign.objects.get(id=cid).status, "queued")

    def _make_queued_campaign(self):
        cid = self._make_campaign()
        self.client.post(
            f"/api/messaging/campaigns/{cid}/build_recipients/",
            data={"sources": ["inquiries"], "manual_emails": []},
            content_type="application/json",
        )
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/queue/")
        self.assertEqual(resp.status_code, 200)
        return cid

    def test_staff_can_pause_queued_campaign(self):
        cid = self._make_queued_campaign()
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/pause/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "paused")
        self.assertEqual(Campaign.objects.get(id=cid).status, "paused")

    def test_staff_can_resume_paused_campaign(self):
        cid = self._make_queued_campaign()
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/pause/")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/resume/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "queued")
        self.assertEqual(Campaign.objects.get(id=cid).status, "queued")

    def test_pausing_draft_campaign_is_rejected(self):
        cid = self._make_campaign()
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/pause/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Campaign.objects.get(id=cid).status, "draft")

    def test_anonymous_cannot_pause(self):
        cid = self._make_queued_campaign()
        self.client.logout()
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/pause/")
        self.assertIn(resp.status_code, (401, 403))
        self.assertEqual(Campaign.objects.get(id=cid).status, "queued")
