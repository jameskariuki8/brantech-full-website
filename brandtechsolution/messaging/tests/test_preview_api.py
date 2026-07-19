from django.contrib.auth.models import User
from django.test import TestCase


class PlaceholderApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def test_anonymous_denied(self):
        self.assertIn(
            self.client.get("/api/messaging/placeholders/").status_code, (401, 403)
        )

    def test_staff_gets_registry(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/api/messaging/placeholders/")
        self.assertEqual(resp.status_code, 200)
        keys = {entry["key"] for entry in resp.json()}
        self.assertIn("first_name", keys)
        self.assertIn("unsubscribe_url", keys)
        for entry in resp.json():
            self.assertIn("label", entry)
            self.assertIn("description", entry)


class PreviewApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def test_anonymous_denied(self):
        resp = self.client.post(
            "/api/messaging/preview/",
            data={"subject": "s", "body_source": "<p>x</p>"},
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (401, 403))

    def _preview(self, subject, body_source):
        self.client.force_login(self.staff)
        return self.client.post(
            "/api/messaging/preview/",
            data={"subject": subject, "body_source": body_source},
            content_type="application/json",
        )

    def test_renders_sample_values_and_inlines_css(self):
        resp = self._preview("Hi {{ first_name }}", "<p>Hello {{ first_name }}</p>")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["subject"], "Hi Ada")
        self.assertIn("Hello Ada", data["body_html"])
        self.assertIn("style=", data["body_html"])

    def test_reports_unknown_placeholders_from_subject_and_body(self):
        resp = self._preview("{{ nope }}", "<p>{{ alsonope }} {{ name }}</p>")
        self.assertEqual(sorted(resp.json()["unknown"]), ["alsonope", "nope"])

    def test_sanitizes_before_rendering(self):
        resp = self._preview("s", "<p>ok</p><script>alert(1)</script>")
        self.assertNotIn("script", resp.json()["body_html"])
