from django.contrib.auth.models import User
from django.test import TestCase
from messaging.models import Inquiry


class InquiryApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.inq = Inquiry.objects.create(name="A", email="a@x.com", message="m")

    def test_anonymous_cannot_list(self):
        resp = self.client.get("/api/messaging/inquiries/")
        self.assertIn(resp.status_code, (401, 403))

    def test_staff_can_list(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/api/messaging/inquiries/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_staff_can_update_status(self):
        self.client.force_login(self.staff)
        resp = self.client.patch(
            f"/api/messaging/inquiries/{self.inq.id}/",
            data={"status": "read"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.inq.refresh_from_db()
        self.assertEqual(self.inq.status, "read")

    def test_staff_can_delete(self):
        self.client.force_login(self.staff)
        resp = self.client.delete(f"/api/messaging/inquiries/{self.inq.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Inquiry.objects.count(), 0)
