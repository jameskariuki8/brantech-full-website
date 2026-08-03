from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase


class TaskSectionVisibilityTest(TestCase):
    """The board is ungated; the controls on it are not.

    This is the one design decision most likely to be "tidied" later into a
    {% if can.manage_tasks %} wrapper to match the sections around it, which
    would hide their own work from every staff member who cannot assign it.
    """

    def test_section_renders_for_a_staff_member_with_no_capabilities(self):
        user = User.objects.create_user("nobody", password="pw", is_staff=True)
        self.client.force_login(user)

        response = self.client.get("/admin-panel/")

        self.assertContains(response, 'id="taskList"')
        self.assertContains(response, "showSection('tasks'")

    def test_manage_tasks_is_not_leaked_to_someone_without_it(self):
        user = User.objects.create_user("nobody", password="pw", is_staff=True)
        self.client.force_login(user)

        response = self.client.get("/admin-panel/")

        # The capability list drives the JS gate. Absent means the New task
        # button stays hidden - and the API refuses regardless.
        self.assertNotContains(response, "manage_tasks")

    def test_capability_is_advertised_to_a_holder(self):
        user = User.objects.create_user("boss", password="pw", is_staff=True)
        group = Group.objects.create(name="Leads")
        group.permissions.add(
            Permission.objects.get(
                codename="manage_tasks", content_type__app_label="staff"
            )
        )
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.get("/admin-panel/")

        self.assertContains(response, "manage_tasks")


class PresetRoleTest(TestCase):
    def test_administrator_preset_can_assign_work(self):
        """0007 grants it. Without this the section ships dead for everyone
        holding the Administrator role rather than a superuser flag."""
        group = Group.objects.get(name="Administrator")

        self.assertTrue(
            group.permissions.filter(
                codename="manage_tasks", content_type__app_label="staff"
            ).exists()
        )

    def test_scoped_presets_are_left_alone(self):
        for name in ("Editor", "Marketing", "Support"):
            with self.subTest(role=name):
                group = Group.objects.get(name=name)
                self.assertFalse(
                    group.permissions.filter(codename="manage_tasks").exists()
                )
