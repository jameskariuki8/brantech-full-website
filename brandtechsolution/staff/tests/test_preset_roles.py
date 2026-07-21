from django.contrib.auth.models import Group
from django.test import TestCase

from staff.capabilities import CODENAMES

EXPECTED = {
    "Editor": {"manage_blog", "publish_blog", "manage_projects"},
    "Marketing": {"manage_templates", "manage_campaigns", "manage_recipients"},
    "Support": {"view_inbox", "handle_inquiries", "manage_appointments"},
    "Administrator": set(CODENAMES),
}


class PresetRoleTest(TestCase):
    def test_all_four_presets_exist(self):
        self.assertEqual(
            sorted(Group.objects.values_list("name", flat=True)),
            sorted(EXPECTED),
        )

    def test_each_preset_has_the_expected_capabilities(self):
        for name, codenames in EXPECTED.items():
            with self.subTest(role=name):
                group = Group.objects.get(name=name)
                actual = set(
                    group.permissions.values_list("codename", flat=True)
                )
                self.assertEqual(actual, codenames)

    def test_marketing_cannot_send_campaigns(self):
        """Sending is reserved to administrators by default."""
        marketing = Group.objects.get(name="Marketing")
        self.assertNotIn(
            "send_campaigns",
            marketing.permissions.values_list("codename", flat=True),
        )

    def test_administrator_can_send_campaigns(self):
        admin = Group.objects.get(name="Administrator")
        self.assertIn(
            "send_campaigns",
            admin.permissions.values_list("codename", flat=True),
        )
