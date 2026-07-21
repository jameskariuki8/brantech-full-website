import json

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from staff.models import AuditEntry


def staff_with(*codenames, username="cap"):
    user = User.objects.create_user(username, password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class PeopleListTest(TestCase):
    def test_requires_manage_staff(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/staff/people/").status_code, 403)

    def test_lists_only_staff_accounts(self):
        admin = staff_with("manage_staff")
        User.objects.create_user("public_signup", password="p")  # not staff
        self.client.force_login(admin)
        resp = self.client.get("/api/staff/people/")
        usernames = [p["username"] for p in resp.json()["results"]]
        self.assertIn("cap", usernames)
        self.assertNotIn("public_signup", usernames)

    def test_includes_roles_and_active_state(self):
        admin = staff_with("manage_staff")
        Group.objects.get(name="Editor").user_set.add(admin)
        self.client.force_login(admin)
        person = self.client.get("/api/staff/people/").json()["results"][0]
        self.assertEqual(person["roles"], ["Editor"])
        self.assertTrue(person["is_active"])


class RoleAssignmentTest(TestCase):
    def setUp(self):
        self.admin = staff_with("manage_staff", username="admin")
        self.target = staff_with(username="target")
        self.client.force_login(self.admin)

    def test_assign_roles(self):
        editor = Group.objects.get(name="Editor")
        resp = self.client.patch(
            f"/api/staff/people/{self.target.pk}/",
            json.dumps({"role_ids": [editor.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(self.target.groups.all()), [editor])

    def test_assignment_is_audited(self):
        editor = Group.objects.get(name="Editor")
        self.client.patch(
            f"/api/staff/people/{self.target.pk}/",
            json.dumps({"role_ids": [editor.pk]}),
            content_type="application/json",
        )
        entry = AuditEntry.objects.get(action="roles_changed")
        self.assertEqual(entry.target_user, self.target)
        self.assertEqual(entry.detail["after"], ["Editor"])

    def test_deactivate_a_user(self):
        resp = self.client.patch(
            f"/api/staff/people/{self.target.pk}/",
            json.dumps({"is_active": False}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertTrue(AuditEntry.objects.filter(action="user_deactivated").exists())

    def test_reactivate_a_user(self):
        self.target.is_active = False
        self.target.save(update_fields=["is_active"])
        self.client.patch(
            f"/api/staff/people/{self.target.pk}/",
            json.dumps({"is_active": True}),
            content_type="application/json",
        )
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertTrue(AuditEntry.objects.filter(action="user_reactivated").exists())


class SelfLockoutTest(TestCase):
    def setUp(self):
        self.admin = staff_with("manage_staff", username="admin")
        self.client.force_login(self.admin)

    def test_cannot_change_own_roles(self):
        editor = Group.objects.get(name="Editor")
        resp = self.client.patch(
            f"/api/staff/people/{self.admin.pk}/",
            json.dumps({"role_ids": [editor.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(list(self.admin.groups.all()), [])

    def test_cannot_deactivate_self(self):
        resp = self.client.patch(
            f"/api/staff/people/{self.admin.pk}/",
            json.dumps({"is_active": False}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_superuser_may_edit_own_roles(self):
        root = User.objects.create_superuser("root", password="p")
        self.client.force_login(root)
        editor = Group.objects.get(name="Editor")
        resp = self.client.patch(
            f"/api/staff/people/{root.pk}/",
            json.dumps({"role_ids": [editor.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
