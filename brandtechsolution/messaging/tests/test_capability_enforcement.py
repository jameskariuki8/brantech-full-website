from django.contrib.auth.models import Permission, User
from django.test import TestCase

from messaging.models import Campaign, EmailTemplate, Inquiry


def staff_with(*codenames):
    user = User.objects.create_user(
        f"u{abs(hash(codenames)) % 100000}", password="p", is_staff=True
    )
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class InquiryCapabilityTest(TestCase):
    def setUp(self):
        Inquiry.objects.create(name="n", email="a@b.com", message="m")

    def test_view_inbox_allows_reading(self):
        self.client.force_login(staff_with("view_inbox"))
        self.assertEqual(self.client.get("/api/messaging/inquiries/").status_code, 200)

    def test_no_capability_cannot_read(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/messaging/inquiries/").status_code, 403)

    def test_view_inbox_alone_cannot_write(self):
        inquiry = Inquiry.objects.first()
        self.client.force_login(staff_with("view_inbox"))
        resp = self.client.patch(
            f"/api/messaging/inquiries/{inquiry.pk}/",
            {"status": "archived"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_handle_inquiries_can_write(self):
        inquiry = Inquiry.objects.first()
        self.client.force_login(staff_with("view_inbox", "handle_inquiries"))
        resp = self.client.patch(
            f"/api/messaging/inquiries/{inquiry.pk}/",
            {"status": "archived"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)


class TemplateCapabilityTest(TestCase):
    def test_requires_manage_templates(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/messaging/templates/").status_code, 403)

    def test_manage_templates_allows_access(self):
        self.client.force_login(staff_with("manage_templates"))
        self.assertEqual(self.client.get("/api/messaging/templates/").status_code, 200)


class CampaignSendCapabilityTest(TestCase):
    """The central case: building a campaign is separate from sending it."""

    def setUp(self):
        self.campaign = Campaign.objects.create(
            name="c", subject="s", body_source="<p>b</p>", body_html="<p>b</p>",
            status="draft", total=5,
        )

    def test_manage_campaigns_can_edit_but_not_queue(self):
        self.client.force_login(staff_with("manage_campaigns"))
        self.assertEqual(
            self.client.get(f"/api/messaging/campaigns/{self.campaign.pk}/").status_code,
            200,
        )
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/queue/")
        self.assertEqual(resp.status_code, 403)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, "draft")

    def test_send_campaigns_can_queue(self):
        self.client.force_login(staff_with("manage_campaigns", "send_campaigns"))
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/queue/")
        self.assertEqual(resp.status_code, 200)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, "queued")

    def test_pause_requires_send_campaigns(self):
        self.campaign.status = "queued"
        self.campaign.save(update_fields=["status"])
        self.client.force_login(staff_with("manage_campaigns"))
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/pause/")
        self.assertEqual(resp.status_code, 403)

    def test_resume_requires_send_campaigns(self):
        self.campaign.status = "paused"
        self.campaign.save(update_fields=["status"])
        self.client.force_login(staff_with("manage_campaigns"))
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/resume/")
        self.assertEqual(resp.status_code, 403)

    def test_build_recipients_requires_manage_recipients(self):
        self.client.force_login(staff_with("manage_campaigns"))
        resp = self.client.post(
            f"/api/messaging/campaigns/{self.campaign.pk}/build_recipients/",
            {"sources": [], "manual_emails": []},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_superuser_can_do_everything(self):
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/queue/")
        self.assertEqual(resp.status_code, 200)


class RecipientCapabilityTest(TestCase):
    def test_requires_manage_recipients(self):
        campaign = Campaign.objects.create(
            name="c", subject="s", body_source="<p>b</p>", body_html="<p>b</p>",
        )
        self.client.force_login(staff_with("manage_campaigns"))
        resp = self.client.get(f"/api/messaging/recipients/?campaign={campaign.pk}")
        self.assertEqual(resp.status_code, 403)


class HelperEndpointCapabilityTest(TestCase):
    def test_placeholders_requires_manage_campaigns(self):
        self.client.force_login(staff_with())
        self.assertEqual(
            self.client.get("/api/messaging/placeholders/").status_code, 403
        )

    def test_placeholders_allowed_with_manage_campaigns(self):
        self.client.force_login(staff_with("manage_campaigns"))
        self.assertEqual(
            self.client.get("/api/messaging/placeholders/").status_code, 200
        )
