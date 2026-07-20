from django.contrib.auth.models import User
from django.test import TestCase
from appointments.models import Appointment
from messaging.models import Campaign, CampaignExclusion, CampaignRecipient, Inquiry, Suppression
from messaging import audience
from messaging.audience import build_recipients


class AudienceTests(TestCase):
    def setUp(self):
        Inquiry.objects.create(name="Ada", email="ada@x.com", message="m")
        User.objects.create_user("u1", email="user@x.com", password="p")
        Appointment.objects.create(
            email="client@x.com", phone="1", full_name="Client C",
            title="t", description="d", date="2026-01-01", time="10:00",
            estimated_duration=30,
        )

    def test_resolve_merges_and_dedupes(self):
        result = audience.resolve_recipients(
            ["inquiries", "users", "appointments"],
            manual_emails=["ada@x.com", "Extra@X.com"],  # dupe of ada + one new
        )
        emails = sorted(r["email"] for r in result)
        self.assertEqual(
            emails, ["ada@x.com", "client@x.com", "extra@x.com", "user@x.com"]
        )

    def test_resolve_excludes_suppressed(self):
        Suppression.objects.create(email="ada@x.com")
        result = audience.resolve_recipients(["inquiries"], manual_emails=[])
        self.assertEqual(result, [])

    def test_resolve_excludes_suppressed_case_insensitively(self):
        Suppression.objects.create(email="ADA@X.com")
        result = audience.resolve_recipients(["inquiries"], manual_emails=[])
        self.assertEqual(result, [])

    def test_resolve_populates_name_from_source(self):
        result = audience.resolve_recipients(["appointments"], manual_emails=[])
        self.assertEqual(result[0]["name"], "Client C")

    def test_build_recipients_creates_rows_and_sets_total(self):
        c = Campaign.objects.create(name="C", subject="s", body_html="<p>x</p>")
        n = audience.build_recipients(c, ["inquiries"], manual_emails=["new@x.com"])
        c.refresh_from_db()
        self.assertEqual(n, 2)
        self.assertEqual(c.total, 2)
        self.assertEqual(CampaignRecipient.objects.filter(campaign=c).count(), 2)


class BuildRecipientsValidationTests(TestCase):
    def _campaign(self):
        return Campaign.objects.create(
            name="C", subject="S", body_source="<p>x</p>", body_html="<p>x</p>"
        )

    def test_well_formed_address_is_marked_valid(self):
        campaign = self._campaign()
        build_recipients(campaign, [], ["ada@example.com"])
        row = CampaignRecipient.objects.get(campaign=campaign, email="ada@example.com")
        self.assertEqual(row.validation_status, "valid")

    def test_malformed_address_is_marked_invalid_syntax(self):
        campaign = self._campaign()
        build_recipients(campaign, [], ["not-an-email"])
        row = CampaignRecipient.objects.get(campaign=campaign, email="not-an-email")
        self.assertEqual(row.validation_status, "invalid_syntax")

    def test_build_does_not_stamp_validated_at(self):
        # Syntax is checked at build; the MX pass is a separate, explicit action.
        campaign = self._campaign()
        build_recipients(campaign, [], ["ada@example.com"])
        row = CampaignRecipient.objects.get(campaign=campaign, email="ada@example.com")
        self.assertIsNone(row.validated_at)


class BuildRecipientsExclusionTests(TestCase):
    def _campaign(self, name="C"):
        return Campaign.objects.create(
            name=name, subject="S", body_source="<p>x</p>", body_html="<p>x</p>"
        )

    def test_build_recipients_drops_excluded_addresses(self):
        campaign = self._campaign()
        CampaignExclusion.objects.create(campaign=campaign, email="ada@example.com")
        n = build_recipients(campaign, [], ["ada@example.com", "bob@example.com"])
        self.assertEqual(n, 1)
        emails = set(
            CampaignRecipient.objects.filter(campaign=campaign).values_list("email", flat=True)
        )
        self.assertEqual(emails, {"bob@example.com"})
        campaign.refresh_from_db()
        self.assertEqual(campaign.total, 1)

    def test_build_recipients_exclusion_matching_is_case_insensitive(self):
        campaign = self._campaign()
        CampaignExclusion.objects.create(campaign=campaign, email="ADA@EXAMPLE.COM")
        n = build_recipients(campaign, [], ["ada@example.com"])
        self.assertEqual(n, 0)
        self.assertFalse(
            CampaignRecipient.objects.filter(campaign=campaign, email="ada@example.com").exists()
        )

    def test_exclusions_are_scoped_per_campaign(self):
        campaign_a = self._campaign(name="A")
        campaign_b = self._campaign(name="B")
        CampaignExclusion.objects.create(campaign=campaign_a, email="ada@example.com")
        n = build_recipients(campaign_b, [], ["ada@example.com"])
        self.assertEqual(n, 1)
        self.assertTrue(
            CampaignRecipient.objects.filter(campaign=campaign_b, email="ada@example.com").exists()
        )
