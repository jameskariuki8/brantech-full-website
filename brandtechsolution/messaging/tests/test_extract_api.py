from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase


class ExtractApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def _file(self):
        return SimpleUploadedFile("c.txt", b"a@x.com b@x.com", content_type="text/plain")

    def test_anonymous_forbidden(self):
        resp = self.client.post("/api/messaging/extract-emails/", {"file": self._file()})
        self.assertIn(resp.status_code, (401, 403))

    def test_staff_extracts_emails(self):
        self.client.force_login(self.staff)
        resp = self.client.post("/api/messaging/extract-emails/", {"file": self._file()})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(sorted(resp.json()["emails"]), ["a@x.com", "b@x.com"])
        self.assertEqual(resp.json()["count"], 2)

    def test_unsupported_type_rejected(self):
        self.client.force_login(self.staff)
        f = SimpleUploadedFile("p.png", b"\x89PNG", content_type="image/png")
        resp = self.client.post("/api/messaging/extract-emails/", {"file": f})
        self.assertEqual(resp.status_code, 400)
