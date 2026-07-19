from django.contrib.auth.models import User
from django.test import TestCase

from messaging.models import Campaign, EmailTemplate


class BodySourceApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.client.force_login(self.staff)

    def test_template_stores_source_and_derives_inlined_html(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "Welcome", "subject": "Hi", "body_source": "<p>Hello</p>",
        })
        self.assertEqual(resp.status_code, 201)
        tpl = EmailTemplate.objects.get()
        self.assertEqual(tpl.body_source, "<p>Hello</p>")
        self.assertIn("style=", tpl.body_html)

    def test_body_html_is_read_only(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s",
            "body_source": "<p>real</p>", "body_html": "<p>ignored</p>",
        })
        self.assertEqual(resp.status_code, 201)
        tpl = EmailTemplate.objects.get()
        self.assertNotIn("ignored", tpl.body_html)
        self.assertIn("real", tpl.body_html)

    def test_source_is_sanitized_on_save(self):
        self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s",
            "body_source": "<p>ok</p><script>alert(1)</script>",
        })
        tpl = EmailTemplate.objects.get()
        self.assertNotIn("script", tpl.body_source)
        self.assertNotIn("script", tpl.body_html)

    def test_edit_round_trip_leaves_source_stable(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s", "body_source": "<p>Hello</p>",
        })
        tpl_id = resp.json()["id"]
        first_source = EmailTemplate.objects.get(id=tpl_id).body_source
        # Re-save exactly what the editor would send back.
        self.client.put(
            f"/api/messaging/templates/{tpl_id}/",
            data={"name": "T", "subject": "s", "body_source": first_source},
            content_type="application/json",
        )
        second_source = EmailTemplate.objects.get(id=tpl_id).body_source
        self.assertEqual(first_source, second_source)
        self.assertNotIn("style=", second_source)

    def test_campaign_also_derives_body_html(self):
        resp = self.client.post("/api/messaging/campaigns/", data={
            "name": "C", "subject": "s", "body_source": "<p>Hi</p>",
        })
        self.assertEqual(resp.status_code, 201)
        campaign = Campaign.objects.get()
        self.assertEqual(campaign.body_source, "<p>Hi</p>")
        self.assertIn("style=", campaign.body_html)

    def test_template_without_body_source_is_rejected(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("body_source", resp.json())
        self.assertEqual(EmailTemplate.objects.count(), 0)

    def test_template_with_blank_body_source_is_rejected(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s", "body_source": "",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("body_source", resp.json())
        self.assertEqual(EmailTemplate.objects.count(), 0)

    def test_campaign_without_body_source_is_rejected(self):
        resp = self.client.post("/api/messaging/campaigns/", data={
            "name": "C", "subject": "s",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("body_source", resp.json())
        self.assertEqual(Campaign.objects.count(), 0)

    def test_patch_template_subject_only_leaves_body_html_unchanged(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s", "body_source": "<p>Hello</p>",
        })
        tpl_id = resp.json()["id"]
        original_html = EmailTemplate.objects.get(id=tpl_id).body_html
        resp = self.client.patch(
            f"/api/messaging/templates/{tpl_id}/",
            data='{"subject": "new subject"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        tpl = EmailTemplate.objects.get(id=tpl_id)
        self.assertEqual(tpl.subject, "new subject")
        self.assertEqual(tpl.body_html, original_html)

    def test_patch_campaign_subject_only_leaves_body_html_unchanged(self):
        resp = self.client.post("/api/messaging/campaigns/", data={
            "name": "C", "subject": "s", "body_source": "<p>Hello</p>",
        })
        campaign_id = resp.json()["id"]
        original_html = Campaign.objects.get(id=campaign_id).body_html
        resp = self.client.patch(
            f"/api/messaging/campaigns/{campaign_id}/",
            data='{"subject": "new subject"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        campaign = Campaign.objects.get(id=campaign_id)
        self.assertEqual(campaign.subject, "new subject")
        self.assertEqual(campaign.body_html, original_html)
