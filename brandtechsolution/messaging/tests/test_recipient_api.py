from django.contrib.auth.models import User
from django.test import TestCase

from messaging.models import Campaign, CampaignRecipient, Suppression


class RecipientApiTestBase(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.client.force_login(self.staff)
        self.campaign = self._campaign()

    def _campaign(self, name="Launch", status="draft", total=0):
        return Campaign.objects.create(
            name=name, subject="S", body_source="<p>x</p>", body_html="<p>x</p>",
            status=status, total=total,
        )

    def _recipient(self, campaign=None, email="ada@example.com", **kwargs):
        return CampaignRecipient.objects.create(
            campaign=campaign or self.campaign, email=email, **kwargs
        )


class RecipientListTests(RecipientApiTestBase):
    def test_list_requires_a_campaign(self):
        resp = self.client.get("/api/messaging/recipients/")
        self.assertEqual(resp.status_code, 400)

    def test_list_rejects_a_non_numeric_campaign(self):
        resp = self.client.get("/api/messaging/recipients/?campaign=abc")
        self.assertEqual(resp.status_code, 400)

    def test_list_returns_only_that_campaigns_recipients(self):
        self._recipient(email="mine@example.com")
        other = self._campaign(name="Other")
        self._recipient(campaign=other, email="theirs@example.com")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertEqual(resp.status_code, 200)
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["mine@example.com"])

    def test_list_is_paginated(self):
        for i in range(55):
            self._recipient(email=f"user{i}@example.com")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        body = resp.json()
        self.assertEqual(body["count"], 55)
        self.assertEqual(len(body["results"]), 50)
        self.assertIsNotNone(body["next"])

    def test_search_matches_email(self):
        self._recipient(email="ada@example.com")
        self._recipient(email="bob@other.com")
        resp = self.client.get(
            f"/api/messaging/recipients/?campaign={self.campaign.id}&search=ADA"
        )
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["ada@example.com"])

    def test_search_matches_name(self):
        self._recipient(email="a@x.com", name="Ada Lovelace")
        self._recipient(email="b@x.com", name="Bob")
        resp = self.client.get(
            f"/api/messaging/recipients/?campaign={self.campaign.id}&search=lovelace"
        )
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["a@x.com"])

    def test_response_exposes_validation_status(self):
        self._recipient(validation_status="invalid_domain")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertEqual(resp.json()["results"][0]["validation_status"], "invalid_domain")

    def test_anonymous_cannot_list(self):
        self.client.logout()
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertIn(resp.status_code, (401, 403))


class RecipientAddTests(RecipientApiTestBase):
    def _add(self, email, name="", campaign=None):
        return self.client.post(
            "/api/messaging/recipients/",
            data={
                "campaign": (campaign or self.campaign).id,
                "email": email,
                "name": name,
            },
            content_type="application/json",
        )

    def test_add_creates_a_pending_recipient(self):
        resp = self._add("ada@example.com", name="Ada")
        self.assertEqual(resp.status_code, 201)
        row = CampaignRecipient.objects.get(campaign=self.campaign)
        self.assertEqual(row.email, "ada@example.com")
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.validation_status, "valid")

    def test_add_normalises_case_and_whitespace(self):
        resp = self._add("  ADA@Example.COM  ")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            CampaignRecipient.objects.filter(
                campaign=self.campaign, email="ada@example.com"
            ).exists()
        )

    def test_add_increments_campaign_total(self):
        self._add("ada@example.com")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 1)

    def test_duplicate_within_campaign_is_rejected(self):
        self._add("ada@example.com")
        resp = self._add("ada@example.com")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(CampaignRecipient.objects.filter(campaign=self.campaign).count(), 1)

    def test_duplicate_check_is_case_insensitive(self):
        self._add("ada@example.com")
        resp = self._add("ADA@EXAMPLE.COM")
        self.assertEqual(resp.status_code, 400)

    def test_suppressed_address_is_rejected(self):
        Suppression.objects.create(email="ada@example.com")
        resp = self._add("ada@example.com")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CampaignRecipient.objects.filter(campaign=self.campaign).exists())

    def test_malformed_address_is_rejected(self):
        # An address Django's own EmailField rejects never reaches the database.
        resp = self._add("not-an-email")
        self.assertEqual(resp.status_code, 400)

    def test_add_to_sending_campaign_is_allowed(self):
        sending = self._campaign(name="InFlight", status="sending")
        resp = self._add("ada@example.com", campaign=sending)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(CampaignRecipient.objects.get(campaign=sending).status, "pending")

    def test_add_to_paused_campaign_is_allowed(self):
        paused = self._campaign(name="Paused", status="paused")
        resp = self._add("ada@example.com", campaign=paused)
        self.assertEqual(resp.status_code, 201)

    def test_add_to_sent_campaign_is_rejected(self):
        finished = self._campaign(name="Done", status="sent")
        resp = self._add("ada@example.com", campaign=finished)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CampaignRecipient.objects.filter(campaign=finished).exists())

    def test_add_to_failed_campaign_is_rejected(self):
        finished = self._campaign(name="Dead", status="failed")
        resp = self._add("ada@example.com", campaign=finished)
        self.assertEqual(resp.status_code, 400)

    def test_anonymous_cannot_add(self):
        self.client.logout()
        resp = self._add("ada@example.com")
        self.assertIn(resp.status_code, (401, 403))
        self.assertFalse(CampaignRecipient.objects.exists())
