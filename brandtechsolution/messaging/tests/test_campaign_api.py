from django.contrib.auth.models import User
from django.test import TestCase
from messaging.models import Campaign, CampaignRecipient, Inquiry


class CampaignApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.client.force_login(self.staff)
        Inquiry.objects.create(name="Ada", email="ada@x.com", message="m")

    def _make_campaign(self):
        resp = self.client.post("/api/messaging/campaigns/", data={
            "name": "Launch", "subject": "Hello", "body_html": "<p>Hi {{ name }}</p>",
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
