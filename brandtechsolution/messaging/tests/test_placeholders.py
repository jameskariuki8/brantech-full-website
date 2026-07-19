from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from messaging import placeholders
from messaging.models import Campaign, CampaignRecipient


class PlaceholderTests(TestCase):
    def setUp(self):
        self.campaign = Campaign.objects.create(
            name="C", subject="s", body_html="<p>x</p>"
        )
        self.recipient = CampaignRecipient.objects.create(
            campaign=self.campaign, email="ada@example.com", name="Ada Lovelace"
        )

    def test_build_context_core_keys(self):
        now = timezone.make_aware(datetime(2026, 7, 19, 12, 0))
        ctx = placeholders.build_context(self.recipient, "http://u/1", now=now)
        self.assertEqual(ctx["name"], "Ada Lovelace")
        self.assertEqual(ctx["first_name"], "Ada")
        self.assertEqual(ctx["email"], "ada@example.com")
        self.assertEqual(ctx["date"], "July 19, 2026")
        self.assertEqual(ctx["year"], "2026")
        self.assertEqual(ctx["unsubscribe_url"], "http://u/1")

    def test_first_name_blank_when_name_blank(self):
        r = CampaignRecipient.objects.create(
            campaign=self.campaign, email="x@example.com", name=""
        )
        ctx = placeholders.build_context(r, "http://u/2")
        self.assertEqual(ctx["first_name"], "")
        self.assertEqual(ctx["name"], "")

    def test_extra_overrides_and_stringifies(self):
        ctx = placeholders.build_context(
            self.recipient, "http://u/1", extra={"company": "Analytical Ltd", "n": 5}
        )
        self.assertEqual(ctx["company"], "Analytical Ltd")
        self.assertEqual(ctx["n"], "5")

    def test_find_placeholders_tolerates_whitespace(self):
        found = placeholders.find_placeholders("{{name}} {{ email }} {{  year  }}")
        self.assertEqual(found, ["name", "email", "year"])

    def test_unknown_placeholders_reports_only_unknown_once(self):
        text = "{{ name }} {{ compnay }} {{ compnay }} {{ email }}"
        self.assertEqual(placeholders.unknown_placeholders(text), ["compnay"])

    def test_sample_context_covers_every_registered_key(self):
        samples = placeholders.sample_context()
        self.assertEqual(set(samples), placeholders.PLACEHOLDER_KEYS)
        self.assertTrue(all(v for v in samples.values()))
