from django.contrib.auth.models import Permission, User
from django.test import TestCase


def staff_with(*codenames, username="cap"):
    user = User.objects.create_user(username, password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class NavGatingTest(TestCase):
    def test_staff_nav_hidden_without_manage_staff(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/admin-panel/")
        self.assertNotContains(resp, "showSection('staff'")

    def test_staff_nav_shown_with_manage_staff(self):
        self.client.force_login(staff_with("manage_staff"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, "showSection('staff'")

    def test_campaigns_nav_hidden_without_capability(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/admin-panel/")
        self.assertNotContains(resp, "showSection('campaigns'")

    def test_superuser_sees_everything(self):
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, "showSection('staff'")
        self.assertContains(resp, "showSection('campaigns'")


class CapabilityExposureTest(TestCase):
    def test_capabilities_are_exposed_to_javascript(self):
        self.client.force_login(staff_with("manage_blog", "view_inbox"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, "window.CAPABILITIES")
        self.assertContains(resp, "manage_blog")
        self.assertContains(resp, "view_inbox")

    def test_capabilities_not_held_are_absent(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/admin-panel/")
        self.assertNotContains(resp, "send_campaigns")

    def test_send_campaigns_is_exposed_to_a_holder(self):
        # campaigns.js swaps the Send button for "awaiting an administrator"
        # when send_campaigns is absent. There is no JS harness, so the one
        # half a Django test can pin is that the flag it reads is correct in
        # both directions - the negative case is above.
        self.client.force_login(staff_with("manage_campaigns", "send_campaigns"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, "send_campaigns")


class CapabilityNamingTest(TestCase):
    """`can` is a SimpleNamespace, not a dict, because Django falls back to
    attribute lookup - so with a dict a codename like `items` or `get` would
    resolve to a bound method and render that section for everyone.

    The namespace removes that class of bug, but a codename shadowing a
    dunder or a namespace attribute would still be a trap, so pin the naming
    rule itself rather than only the current implementation.
    """

    def test_no_codename_collides_with_a_dict_or_object_attribute(self):
        from types import SimpleNamespace

        from staff.capabilities import CODENAMES

        collisions = sorted(
            set(CODENAMES) & (set(dir({})) | set(dir(SimpleNamespace())))
        )
        self.assertEqual(collisions, [])

    def test_no_codename_starts_with_an_underscore(self):
        # Django refuses to resolve template variables beginning with "_",
        # so such a capability would silently never gate anything.
        from staff.capabilities import CODENAMES

        self.assertEqual([c for c in CODENAMES if c.startswith("_")], [])


class BlogStatusControlTest(TestCase):
    """The publish_blog capability is unreachable from the panel unless the
    blog form can actually set a status, so the control's presence and its
    gating are asserted here rather than left to inspection."""

    def test_status_control_is_enabled_with_publish_blog(self):
        self.client.force_login(staff_with("manage_blog", "publish_blog"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, 'name="status"')
        self.assertNotContains(resp, 'name="status" disabled')

    def test_status_control_is_disabled_without_publish_blog(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/admin-panel/")
        # Rendered but disabled: a disabled control is omitted from FormData,
        # so an ordinary edit never sends a status key and never trips the
        # publish check on the server.
        self.assertContains(resp, 'name="status" disabled')


class SectionGatingTest(TestCase):
    def test_staff_section_absent_without_manage_staff(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/admin-panel/")
        self.assertNotContains(resp, 'id="staffPeopleList"')

    def test_staff_section_present_with_manage_staff(self):
        self.client.force_login(staff_with("manage_staff"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, 'id="staffPeopleList"')

    def test_blog_section_absent_without_manage_blog(self):
        self.client.force_login(staff_with("view_inbox"))
        resp = self.client.get("/admin-panel/")
        self.assertNotContains(resp, 'id="blogsList"')
