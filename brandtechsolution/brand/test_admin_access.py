from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

PAGES = (
    "/admin/brand/partnershiptype/",
    "/admin/brand/partnerorganisation/",
    "/admin/brand/career/",
)


def staff_user(username, *capabilities):
    user = User.objects.create_user(username, f"{username}@example.com", "pass-12345-abc", is_staff=True)
    if capabilities:
        group = Group.objects.create(name=f"role-{username}")
        group.permissions.set(
            Permission.objects.filter(codename__in=capabilities, content_type__app_label="staff")
        )
        user.groups.add(group)
    return user


class ManageStaffAdminAccessTests(TestCase):
    """The panel's "Partnerships & People" link is shown to Manage staff holders."""

    def test_a_role_with_manage_staff_opens_every_one(self):
        self.client.force_login(staff_user("admin_role", "manage_staff"))
        for path in PAGES:
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_a_role_with_manage_staff_can_add(self):
        self.client.force_login(staff_user("admin_role", "manage_staff"))
        self.assertEqual(self.client.get("/admin/brand/partnershiptype/add/").status_code, 200)

    def test_staff_without_manage_staff_get_the_themed_403(self):
        self.client.force_login(staff_user("blogger", "manage_blog"))
        for path in PAGES:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 403, path)
            self.assertContains(resp, "You don't have access to this page", status_code=403)
            self.assertContains(resp, "/admin-panel/", status_code=403)

    def test_inactive_manage_staff_holder_is_refused(self):
        user = staff_user("gone", "manage_staff")
        self.client.force_login(user)
        user.is_active = False
        user.save()
        self.assertNotEqual(self.client.get(PAGES[0]).status_code, 200)

    def test_superuser_still_gets_in(self):
        root = User.objects.create_superuser("root", "root@example.com", "pass-12345-abc")
        self.client.force_login(root)
        self.assertEqual(self.client.get(PAGES[0]).status_code, 200)


class ThemedForbiddenPageTests(TestCase):
    def test_page_names_the_signed_in_account(self):
        self.client.force_login(staff_user("blogger", "manage_blog"))
        resp = self.client.get(PAGES[0])
        self.assertContains(resp, "blogger@example.com", status_code=403)
