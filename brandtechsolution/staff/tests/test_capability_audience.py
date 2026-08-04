"""Notifications addressed by capability rather than by configuration.

capability_holder_emails has to agree with User.has_perm(), because the same
capability decides both who is told about a draft and who may act on it. A
mismatch means either mailing someone who will be refused at the dashboard, or
staying silent towards someone who is waiting to approve.
"""
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from staff.emails import capability_holder_emails


def grant(user, codename):
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="staff", codename=codename)
    )
    return User.objects.get(pk=user.pk)  # drop the permission cache


class CapabilityHolderEmailsTest(TestCase):
    def setUp(self):
        self.holder = User.objects.create_user(
            "holder", "holder@example.com", "pw", is_staff=True
        )
        grant(self.holder, "publish_blog")

    def test_a_direct_grant_is_included(self):
        self.assertEqual(
            capability_holder_emails("publish_blog"), ["holder@example.com"]
        )

    def test_a_grant_through_a_role_group_is_included(self):
        editors = Group.objects.create(name="Editors")
        editors.permissions.add(
            Permission.objects.get(
                content_type__app_label="staff", codename="publish_blog"
            )
        )
        member = User.objects.create_user(
            "member", "member@example.com", "pw", is_staff=True
        )
        member.groups.add(editors)

        self.assertIn("member@example.com", capability_holder_emails("publish_blog"))

    def test_a_superuser_is_included_without_an_explicit_grant(self):
        User.objects.create_superuser("root", "root@example.com", "pw")
        self.assertIn("root@example.com", capability_holder_emails("publish_blog"))

    def test_holding_a_different_capability_is_not_enough(self):
        other = User.objects.create_user(
            "other", "other@example.com", "pw", is_staff=True
        )
        grant(other, "manage_blog")

        self.assertNotIn("other@example.com", capability_holder_emails("publish_blog"))

    def test_a_non_staff_account_is_excluded(self):
        """staff.decorators refuses these, so they must not be notified."""
        outsider = User.objects.create_user(
            "outsider", "outsider@example.com", "pw", is_staff=False
        )
        grant(outsider, "publish_blog")

        self.assertNotIn(
            "outsider@example.com", capability_holder_emails("publish_blog")
        )

    def test_a_deactivated_account_is_excluded(self):
        """has_perm() is False for an inactive user; this must agree."""
        self.holder.is_active = False
        self.holder.save()

        self.assertEqual(capability_holder_emails("publish_blog"), [])

    def test_an_account_without_an_address_is_excluded(self):
        self.holder.email = ""
        self.holder.save()

        self.assertEqual(capability_holder_emails("publish_blog"), [])

    def test_a_direct_and_group_grant_yields_one_address(self):
        """The permission join emits a row per grant; the caller gets a
        recipient list, so a duplicate would mail the person twice."""
        editors = Group.objects.create(name="Editors")
        editors.permissions.add(
            Permission.objects.get(
                content_type__app_label="staff", codename="publish_blog"
            )
        )
        self.holder.groups.add(editors)

        self.assertEqual(
            capability_holder_emails("publish_blog"), ["holder@example.com"]
        )

    def test_the_result_agrees_with_has_perm(self):
        """The invariant the whole helper rests on."""
        User.objects.create_superuser("root", "root@example.com", "pw")
        User.objects.create_user("nobody", "nobody@example.com", "pw", is_staff=True)

        addressed = set(capability_holder_emails("publish_blog"))
        for user in User.objects.all():
            permitted = user.is_staff and user.has_perm("staff.publish_blog")
            self.assertEqual(
                user.email in addressed,
                permitted and bool(user.email),
                f"{user.username}: addressed={user.email in addressed} "
                f"permitted={permitted}",
            )
