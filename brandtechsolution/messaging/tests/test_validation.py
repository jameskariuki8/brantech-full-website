from unittest.mock import patch

import dns.resolver
from django.core.cache import cache
from django.test import TestCase

from messaging.validation import domain_has_mx, validate_syntax


class ValidateSyntaxTests(TestCase):
    def test_accepts_ordinary_address(self):
        self.assertTrue(validate_syntax("ada@example.com"))

    def test_rejects_address_without_at_sign(self):
        self.assertFalse(validate_syntax("ada-at-example.com"))

    def test_rejects_address_without_domain(self):
        self.assertFalse(validate_syntax("ada@"))

    def test_rejects_blank(self):
        self.assertFalse(validate_syntax(""))

    def test_rejects_none(self):
        self.assertFalse(validate_syntax(None))


class DomainHasMxTests(TestCase):
    def setUp(self):
        # LocMemCache persists for the life of the process, so a verdict cached
        # by one test would leak into the next and mask a real lookup.
        cache.clear()

    def test_domain_with_mx_records_is_valid(self):
        with patch("messaging.validation._query_mx", return_value=["mx1.example.com"]):
            self.assertTrue(domain_has_mx("example.com"))

    def test_nxdomain_is_invalid(self):
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NXDOMAIN):
            self.assertFalse(domain_has_mx("nope.invalid"))

    def test_no_answer_is_invalid(self):
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NoAnswer):
            self.assertFalse(domain_has_mx("no-mx.example.com"))

    def test_timeout_is_invalid_and_does_not_raise(self):
        with patch("messaging.validation._query_mx", side_effect=dns.exception.Timeout):
            self.assertFalse(domain_has_mx("slow.example.com"))

    def test_empty_answer_is_invalid(self):
        with patch("messaging.validation._query_mx", return_value=[]):
            self.assertFalse(domain_has_mx("empty.example.com"))

    def test_result_is_cached_so_repeat_lookups_hit_dns_once(self):
        with patch("messaging.validation._query_mx", return_value=["mx1"]) as q:
            domain_has_mx("example.com")
            domain_has_mx("example.com")
            domain_has_mx("EXAMPLE.COM")
        self.assertEqual(q.call_count, 1)

    def test_negative_result_is_cached_too(self):
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NXDOMAIN) as q:
            self.assertFalse(domain_has_mx("nope.invalid"))
            self.assertFalse(domain_has_mx("nope.invalid"))
        self.assertEqual(q.call_count, 1)

    def test_blank_domain_is_invalid_without_a_lookup(self):
        with patch("messaging.validation._query_mx") as q:
            self.assertFalse(domain_has_mx(""))
        q.assert_not_called()


from messaging.models import Campaign, CampaignRecipient
from messaging.validation import validate_campaign_recipients


class ValidateCampaignRecipientsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.campaign = Campaign.objects.create(
            name="C", subject="S", body_source="<p>x</p>", body_html="<p>x</p>"
        )

    def _recipient(self, email, validation_status="valid"):
        return CampaignRecipient.objects.create(
            campaign=self.campaign, email=email, validation_status=validation_status
        )

    def test_live_domain_stays_valid_and_is_stamped(self):
        row = self._recipient("ada@example.com")
        with patch("messaging.validation._query_mx", return_value=["mx1"]):
            validate_campaign_recipients(self.campaign)
        row.refresh_from_db()
        self.assertEqual(row.validation_status, "valid")
        self.assertIsNotNone(row.validated_at)

    def test_dead_domain_becomes_invalid_domain(self):
        row = self._recipient("ada@nope.invalid")
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NXDOMAIN):
            validate_campaign_recipients(self.campaign)
        row.refresh_from_db()
        self.assertEqual(row.validation_status, "invalid_domain")

    def test_malformed_rows_are_skipped_not_looked_up(self):
        row = self._recipient("not-an-email", validation_status="invalid_syntax")
        with patch("messaging.validation._query_mx") as q:
            validate_campaign_recipients(self.campaign)
        q.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.validation_status, "invalid_syntax")

    def test_shared_domain_costs_one_lookup(self):
        for i in range(5):
            self._recipient(f"user{i}@example.com")
        with patch("messaging.validation._query_mx", return_value=["mx1"]) as q:
            validate_campaign_recipients(self.campaign)
        self.assertEqual(q.call_count, 1)

    def test_returns_counts_for_every_status(self):
        self._recipient("ada@example.com")
        self._recipient("bad", validation_status="invalid_syntax")
        with patch("messaging.validation._query_mx", return_value=["mx1"]):
            counts = validate_campaign_recipients(self.campaign)
        self.assertEqual(
            counts,
            {"valid": 1, "invalid_syntax": 1, "invalid_domain": 0, "unknown": 0},
        )

    def test_other_campaigns_are_untouched(self):
        other = Campaign.objects.create(
            name="Other", subject="S", body_source="<p>x</p>", body_html="<p>x</p>"
        )
        stranger = CampaignRecipient.objects.create(
            campaign=other, email="bob@nope.invalid", validation_status="valid"
        )
        self._recipient("ada@example.com")
        with patch("messaging.validation._query_mx", return_value=["mx1"]):
            validate_campaign_recipients(self.campaign)
        stranger.refresh_from_db()
        self.assertEqual(stranger.validation_status, "valid")
        self.assertIsNone(stranger.validated_at)
