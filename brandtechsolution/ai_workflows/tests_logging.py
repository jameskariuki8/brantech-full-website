"""
Tests for the sensitive-value masking helpers used when logging env overrides
in ai_workflows.service._set_external_environment.

Only synthetic fake values are used here — never a real API key/secret.
"""
from django.test import TestCase

from ai_workflows.service import _is_sensitive, _mask_secret


class IsSensitiveTests(TestCase):
    def test_key_marker_is_sensitive(self):
        self.assertTrue(_is_sensitive("GOOGLE_API_KEY"))

    def test_non_sensitive_key(self):
        self.assertFalse(_is_sensitive("LANGSMITH_TRACING"))

    def test_secret_marker_is_sensitive(self):
        self.assertTrue(_is_sensitive("DJANGO_SECRET"))

    def test_token_marker_is_sensitive(self):
        self.assertTrue(_is_sensitive("AUTH_TOKEN"))

    def test_password_marker_is_sensitive(self):
        self.assertTrue(_is_sensitive("DB_PASSWORD"))

    def test_case_insensitive(self):
        self.assertTrue(_is_sensitive("google_api_key"))


class MaskSecretTests(TestCase):
    def test_long_value_is_masked(self):
        fake_value = "A" * 40
        masked = _mask_secret(fake_value)
        self.assertNotIn(fake_value, masked)
        self.assertTrue(masked.startswith(fake_value[:8]))
        self.assertTrue(masked.endswith(fake_value[-4:]))

    def test_short_value_returns_stars(self):
        self.assertEqual(_mask_secret("short"), "***")
