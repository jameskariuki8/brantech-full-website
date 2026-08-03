import importlib

from django.apps import apps
from django.contrib.auth.models import Group, Permission
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

    def test_create_presets_is_safe_on_a_fresh_database(self):
        """Reproduces the fresh-database ordering trap.

        Django creates auth.Permission rows in a post_migrate handler that
        runs AFTER all migrations, so on a from-scratch database they don't
        exist yet while this data migration runs. If create_presets ever
        regresses to a naive `Permission.objects.filter(...)` lookup instead
        of creating the content type/permissions itself first, it would
        silently build four EMPTY roles instead of failing loudly.
        """
        Group.objects.filter(name__in=EXPECTED).delete()
        Permission.objects.filter(content_type__app_label="staff").delete()

        preset_roles = importlib.import_module(
            "staff.migrations.0002_preset_roles"
        )
        preset_roles.create_presets(apps, None)

        # Compared against the migration's OWN preset table, not EXPECTED.
        # 0002 is history and does not change; capabilities added later are
        # granted by their own migrations (manage_tasks by 0007), so a
        # from-scratch run of 0002 alone legitimately produces the roles as
        # they stood then. Asserting the live registry here would fail on
        # every future capability while telling us nothing about the trap
        # this test exists to catch - which is roles coming out EMPTY.
        for name, codenames in preset_roles.PRESETS.items():
            with self.subTest(role=name):
                group = Group.objects.get(name=name)
                actual = set(
                    group.permissions.values_list("codename", flat=True)
                )
                self.assertEqual(actual, set(codenames))
                self.assertTrue(actual, f"{name} came out empty")
