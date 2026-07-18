from django.db import IntegrityError
from django.test import TestCase
from messaging.models import Campaign, CampaignRecipient


class CampaignModelTests(TestCase):
    def test_campaign_defaults(self):
        c = Campaign.objects.create(name="Launch", subject="Hi", body_html="<p>x</p>")
        self.assertEqual(c.status, "draft")
        self.assertEqual(c.total, 0)
        self.assertEqual(c.sent_count, 0)
        self.assertIsNone(c.started_at)

    def test_recipient_defaults_and_uniqueness(self):
        c = Campaign.objects.create(name="Launch", subject="Hi", body_html="<p>x</p>")
        r = CampaignRecipient.objects.create(campaign=c, email="a@x.com", name="A")
        self.assertEqual(r.status, "pending")
        self.assertEqual(r.attempts, 0)
        with self.assertRaises(IntegrityError):
            CampaignRecipient.objects.create(campaign=c, email="a@x.com")
