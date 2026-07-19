from django.contrib.auth.models import User
from django.test import TestCase
from messaging.models import EmailTemplate


class EmailTemplateApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def test_anonymous_cannot_create(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "Welcome", "subject": "Hi", "body_source": "<p>Hi {{ name }}</p>",
        })
        self.assertIn(resp.status_code, (401, 403))

    def test_staff_can_create_and_list(self):
        self.client.force_login(self.staff)
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "Welcome", "subject": "Hi", "body_source": "<p>Hi {{ name }}</p>",
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(EmailTemplate.objects.count(), 1)
        resp = self.client.get("/api/messaging/templates/")
        self.assertEqual(len(resp.json()), 1)
