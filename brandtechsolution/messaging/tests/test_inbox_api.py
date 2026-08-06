from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from messaging.models import Inquiry

User = get_user_model()


def staff_with_capabilities(*codenames, username="staffuser"):
    user, _ = User.objects.get_or_create(username=username, is_staff=True)
    user.user_permissions.clear()
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)



class InquiryInboxApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.inquiry = Inquiry.objects.create(
            name="Alice Smith",
            email="alice@example.com",
            message="Initial question about software consulting.",
            status="new",
        )
        self.view_user = staff_with_capabilities("view_inbox", username="viewer")
        self.handler_user = staff_with_capabilities("view_inbox", "handle_inquiries", username="handler")

    def test_view_inbox_can_list_and_search(self):
        self.client.force_authenticate(user=self.view_user)

        response = self.client.get("/api/messaging/inquiries/?q=Alice")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)

    def test_view_inbox_only_cannot_reply(self):
        self.client.force_authenticate(user=self.view_user)

        response = self.client.post(
            f"/api/messaging/inquiries/{self.inquiry.pk}/reply/",
            {"message": "Thank you for reaching out!"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_handler_can_reply_mark_read_and_archive(self):
        self.client.force_authenticate(user=self.handler_user)

        # Mark read
        resp1 = self.client.post(f"/api/messaging/inquiries/{self.inquiry.pk}/mark_read/")
        self.assertEqual(resp1.status_code, 200)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, "read")

        # Reply
        resp2 = self.client.post(
            f"/api/messaging/inquiries/{self.inquiry.pk}/reply/",
            {"message": "We would be happy to help with software consulting."},
            format="json",
        )
        self.assertEqual(resp2.status_code, 200)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, "replied")
        self.assertIn("STAFF REPLY (handler)", self.inquiry.message)

        # Archive
        resp3 = self.client.post(f"/api/messaging/inquiries/{self.inquiry.pk}/archive/")
        self.assertEqual(resp3.status_code, 200)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, "archived")
