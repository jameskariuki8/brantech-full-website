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


class CapabilityListTest(TestCase):
    def test_requires_manage_staff(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/staff/capabilities/").status_code, 403)

    def test_returns_the_grouped_registry(self):
        self.client.force_login(staff_with("manage_staff"))
        resp = self.client.get("/api/staff/capabilities/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual([g["label"] for g in data],
                         ["Content", "Communications", "Administration"])
        flat = [c["codename"] for g in data for c in g["capabilities"]]
        self.assertEqual(len(flat), 11)
        self.assertIn("send_campaigns", flat)


class RoleListTest(TestCase):
    def test_requires_manage_staff(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/staff/roles/").status_code, 403)

    def test_lists_presets_with_member_counts(self):
        user = staff_with("manage_staff")
        Group.objects.get(name="Editor").user_set.add(user)
        self.client.force_login(user)
        resp = self.client.get("/api/staff/roles/")
        self.assertEqual(resp.status_code, 200)
        by_name = {r["name"]: r for r in resp.json()["results"]}
        self.assertEqual(by_name["Editor"]["member_count"], 1)
        self.assertEqual(by_name["Marketing"]["member_count"], 0)
        self.assertIn("manage_blog", by_name["Editor"]["capabilities"])


class RoleWriteTest(TestCase):
    def setUp(self):
        self.admin = staff_with("manage_staff")
        self.client.force_login(self.admin)

    def test_create_a_role(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Interns", "capabilities": ["manage_blog"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        group = Group.objects.get(name="Interns")
        self.assertEqual(
            list(group.permissions.values_list("codename", flat=True)), ["manage_blog"]
        )

    def test_create_writes_an_audit_entry(self):
        self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Interns", "capabilities": []}),
            content_type="application/json",
        )
        entry = AuditEntry.objects.get(action="group_created")
        self.assertEqual(entry.actor, self.admin)
        self.assertIn("Interns", entry.summary)

    def test_update_replaces_capabilities_and_records_before_after(self):
        group = Group.objects.get(name="Editor")
        resp = self.client.put(
            f"/api/staff/roles/{group.pk}/",
            json.dumps({"name": "Editor", "capabilities": ["view_inbox"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            list(group.permissions.values_list("codename", flat=True)), ["view_inbox"]
        )
        entry = AuditEntry.objects.get(action="group_updated")
        self.assertIn("manage_blog", entry.detail["before"])
        self.assertEqual(entry.detail["after"], ["view_inbox"])

    def test_unknown_capability_is_rejected(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Bad", "capabilities": ["not_a_capability"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Group.objects.filter(name="Bad").exists())

    def test_duplicate_name_is_rejected(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Editor", "capabilities": []}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_delete_a_role(self):
        group = Group.objects.get(name="Support")
        resp = self.client.delete(f"/api/staff/roles/{group.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Group.objects.filter(name="Support").exists())
        self.assertTrue(AuditEntry.objects.filter(action="group_deleted").exists())
