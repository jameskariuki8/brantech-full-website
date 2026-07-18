from django.contrib.auth.models import User
from django.test import TestCase


class AdminPanelRenderTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def test_panel_renders_for_staff_with_sections(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for anchor in ['id="dashboard"', 'id="blogs"', 'id="projects"']:
            self.assertIn(anchor, html)
