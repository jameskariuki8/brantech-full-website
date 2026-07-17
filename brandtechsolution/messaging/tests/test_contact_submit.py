from django.test import TestCase
from django.urls import reverse
from django.core import mail
from django.test import override_settings
from messaging.models import Inquiry


class ContactSubmitTests(TestCase):
    def _post(self, **overrides):
        data = {
            "name": "Grace Hopper",
            "email": "grace@example.com",
            "phone": "123",
            "message": "I need a website",
            "website": "",  # honeypot, must stay empty
        }
        data.update(overrides)
        return self.client.post(reverse("contact_submit"), data)

    def test_valid_submission_creates_inquiry_and_redirects(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Inquiry.objects.count(), 1)
        inq = Inquiry.objects.get()
        self.assertEqual(inq.email, "grace@example.com")
        self.assertEqual(inq.status, "new")

    def test_honeypot_filled_is_dropped_silently(self):
        resp = self._post(website="http://spam.example")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Inquiry.objects.count(), 0)

    def test_missing_required_fields_does_not_create(self):
        resp = self._post(email="", message="")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Inquiry.objects.count(), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="admin@example.com",
    )
    def test_valid_submission_sends_admin_notification(self):
        self._post()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("grace@example.com", mail.outbox[0].body)
