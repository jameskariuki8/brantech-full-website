from django.contrib.auth.models import User
from django.test import TestCase
from appointments.models import Appointment
from messaging.models import Campaign, CampaignRecipient, Inquiry, Suppression
from messaging import audience


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
