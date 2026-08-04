from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from messaging.models import Inquiry


class ContactSubmitTests(TestCase):
    def setUp(self):
        cache.clear()

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
        # Without a token in the payload an enabled Turnstile refuses the POST
        # before any of this is reached, so the assertion below would pass or
        # fail for reasons unrelated to the notification.
        TURNSTILE_SECRET_KEY="",
    )
    def test_valid_submission_notifies_handle_inquiries_holders(self):
        """Recipients come from the capability, not from a list in the view."""
        handler = User.objects.create_user(
            "handler", "handler@example.com", "pw", is_staff=True
        )
        handler.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="staff", codename="handle_inquiries"
            )
        )

        self._post()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["handler@example.com"])
        self.assertIn("grace@example.com", mail.outbox[0].body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        TURNSTILE_SECRET_KEY="",
    )
    def test_the_inquiry_is_saved_even_when_nobody_can_be_notified(self):
        """The panel's inbox is the record; the email is only an alert.

        A team with nobody holding handle_inquiries must still capture leads.
        """
        self._post()

        self.assertEqual(Inquiry.objects.count(), 1)
        self.assertEqual(mail.outbox, [])

    def test_ajax_valid_submission_returns_json_ok(self):
        data = {
            "name": "Grace Hopper",
            "email": "grace@example.com",
            "phone": "123",
            "message": "I need a website",
            "website": "",
        }
        resp = self.client.post(
            reverse("contact_submit"), data, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})
        self.assertEqual(Inquiry.objects.count(), 1)

    def test_ajax_missing_required_fields_returns_json_error(self):
        data = {
            "name": "Grace Hopper",
            "email": "",
            "phone": "123",
            "message": "",
            "website": "",
        }
        resp = self.client.post(
            reverse("contact_submit"), data, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])
        self.assertEqual(Inquiry.objects.count(), 0)

    def test_ajax_honeypot_filled_returns_json_ok_without_saving(self):
        data = {
            "name": "Grace Hopper",
            "email": "grace@example.com",
            "phone": "123",
            "message": "I need a website",
            "website": "http://spam.example",
        }
        resp = self.client.post(
            reverse("contact_submit"), data, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})
        self.assertEqual(Inquiry.objects.count(), 0)
