from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from messaging.models import Inquiry


class ContactRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def _post(self, ip, **overrides):
        data = {
            "name": "Grace Hopper",
            "email": "grace@example.com",
            "phone": "123",
            "message": "I need a website",
            "website": "",
        }
        data.update(overrides)
        return self.client.post(
            reverse("contact_submit"),
            data,
            HTTP_ACCEPT="application/json",
            HTTP_X_FORWARDED_FOR=ip,
        )

    @override_settings(CONTACT_RATE_LIMIT_COUNT=2)
    def test_third_submission_from_same_ip_is_rate_limited(self):
        resp1 = self._post("1.2.3.4")
        resp2 = self._post("1.2.3.4")
        resp3 = self._post("1.2.3.4")

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp3.status_code, 429)
        self.assertFalse(resp3.json()["ok"])
        self.assertEqual(Inquiry.objects.count(), 2)

    @override_settings(CONTACT_RATE_LIMIT_COUNT=2)
    def test_different_ip_is_not_affected_by_other_ips_limit(self):
        self._post("1.2.3.4")
        self._post("1.2.3.4")
        resp3 = self._post("1.2.3.4")
        self.assertEqual(resp3.status_code, 429)

        resp_other = self._post("9.9.9.9")
        self.assertEqual(resp_other.status_code, 200)
        self.assertEqual(Inquiry.objects.count(), 3)
