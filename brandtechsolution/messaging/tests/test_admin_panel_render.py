from django.contrib.auth.models import Permission, User
from django.test import TestCase


class AdminPanelRenderTests(TestCase):
    def setUp(self):
        # Sections are now gated on capabilities rather than on the bare
        # is_staff flag, so this fixture holds the ones the panel's content
        # sections require. The capability-less case is asserted separately
        # below.
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.staff.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="staff",
                codename__in=[
                    "manage_blog", "manage_projects", "view_inbox",
                    "manage_templates", "manage_campaigns", "manage_recipients",
                ],
            )
        )
        self.staff = User.objects.get(pk=self.staff.pk)

    def test_panel_renders_for_staff_with_sections(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for anchor in [
            'id="dashboard"', 'id="blogs"', 'id="projects"', 'id="inbox"', 'id="templates"', 'id="campaigns"',
            'id="templateEditorContainer"',
            'id="templateSourceToggle"',
            'id="templatePreviewFrame"',
            'id="campaignEditorContainer"',
            'id="campaignPreviewFrame"',
            'id="recipientsModal"',
            'id="recipientsList"',
            'id="addRecipientForm"',
        ]:
            self.assertIn(anchor, html)
        for script in ['core.js', 'blogs.js', 'projects.js', 'inbox.js', 'templates.js', 'campaigns.js', 'editor.js', 'recipients.js', 'staff.js']:
            self.assertIn(script, html)

    def test_panel_renders_bare_for_staff_without_capabilities(self):
        """A staff account with no capabilities still gets a working shell:
        dashboard only, with every script still loaded. Each script guards
        itself against the elements its section would have provided."""
        bare = User.objects.create_user("bare", password="p", is_staff=True)
        self.client.force_login(bare)
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="dashboard"', html)
        for anchor in ['id="blogs"', 'id="projects"', 'id="inbox"',
                       'id="templates"', 'id="campaigns"', 'id="staff"']:
            self.assertNotIn(anchor, html)
        for script in ['core.js', 'blogs.js', 'projects.js', 'inbox.js',
                       'templates.js', 'campaigns.js', 'editor.js',
                       'recipients.js', 'staff.js']:
            self.assertIn(script, html)
