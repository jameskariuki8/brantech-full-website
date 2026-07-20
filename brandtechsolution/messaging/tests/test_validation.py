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
