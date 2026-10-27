import json

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase, override_settings

from messaging.models import SharedMailbox
from staff.models import AuditEntry, StaffInvitation

URL = "/api/staff/roles/"


def staff(username, *codenames, **extra):
    user = User.objects.create_user(username, email=f"{username}@personal.example",
                                    password="p", is_staff=True, **extra)
    if codenames:
        user.user_permissions.add(*Permission.objects.filter(
            codename__in=codenames, content_type__app_label="staff"))
    return User.objects.get(pk=user.pk)


def group(name, *codenames, mailboxes=()):
    g = Group.objects.create(name=name)
    g.permissions.add(*Permission.objects.filter(
        codename__in=codenames, content_type__app_label="staff"))
    g.shared_mailboxes.add(*SharedMailbox.objects.filter(name__in=mailboxes))
    return g


@override_settings(
    MAILBOX_DOMAIN="teklora.co.ke",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class GroupMembersTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser("owner", "owner@personal.example", "p")
        self.ann = staff("ann")
        self.bob = staff("bob")

    def put(self, g, **data):
        body = {"name": g.name, "capabilities": [], **data}
        return self.client.put(f"{URL}{g.pk}/", json.dumps(body), content_type="application/json")

    def test_create_a_group_with_capabilities_mailboxes_and_members(self):
        self.client.force_login(self.owner)
        resp = self.client.post(URL, json.dumps({
            "name": "HR", "capabilities": ["manage_appointments"],
            "mailboxes": ["hr", "careers"], "member_ids": [self.ann.pk, self.bob.pk],
        }), content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(data["mailboxes"], ["careers", "hr"])
        self.assertEqual([m["username"] for m in data["members"]], ["ann", "bob"])
        self.assertEqual(data["member_count"], 2)
        self.assertTrue(self.ann.groups.filter(name="HR").exists())
        # One entry for the group, one per person added.
        self.assertEqual(AuditEntry.objects.filter(action="group_created").count(), 1)
        self.assertEqual(AuditEntry.objects.filter(action="roles_changed").count(), 2)

    def test_member_ids_replace_the_membership(self):
        g = group("HR")
        self.ann.groups.add(g)
        self.client.force_login(self.owner)
        resp = self.put(g, member_ids=[self.bob.pk])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(list(g.user_set.values_list("username", flat=True)), ["bob"])
        entry = AuditEntry.objects.get(action="roles_changed", target_user=self.ann)
        self.assertEqual((entry.detail["before"], entry.detail["after"]), (["HR"], []))

    def test_leaving_member_ids_out_keeps_the_membership(self):
        g = group("HR")
        self.ann.groups.add(g)
        self.client.force_login(self.owner)
        self.put(g, capabilities=["manage_blog"])
        self.assertTrue(self.ann.groups.filter(pk=g.pk).exists())

    def test_only_staff_accounts_can_be_members(self):
        outsider = User.objects.create_user("outsider", email="o@example.com")
        g = group("HR")
        self.client.force_login(self.owner)
        self.assertEqual(self.put(g, member_ids=[outsider.pk]).status_code, 400)

    def test_listing_shows_members_mailboxes_and_pending_invitations(self):
        g = group("HR", mailboxes=["hr"])
        self.ann.groups.add(g)
        invite = StaffInvitation.objects.create(email="new@example.com")
        invite.groups.add(g)
        self.client.force_login(self.owner)
        [row] = [r for r in self.client.get(URL).json()["results"] if r["name"] == "HR"]
        self.assertEqual(row["mailboxes"], ["hr"])
        self.assertEqual([m["username"] for m in row["members"]], ["ann"])
        self.assertEqual(row["invited"], ["new@example.com"])

    def test_inviting_into_a_group(self):
        g = group("HR", mailboxes=["hr"])
        self.client.force_login(self.owner)
        resp = self.client.post("/api/staff/invitations/", json.dumps(
            {"email": "new@example.com", "role_ids": [g.pk]}), content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(list(StaffInvitation.objects.get().groups.all()), [g])


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class GroupGrantLimitsTest(TestCase):
    """A manage_staff holder who is not the superuser can only hand out what
    they hold, through any of the group editor's doors."""

    def setUp(self):
        self.manager = staff("manager", "manage_staff", "manage_blog")
        self.ann = staff("ann")
        self.client.force_login(self.manager)

    def put(self, g, **data):
        body = {"name": g.name, "capabilities": [], **data}
        return self.client.put(f"{URL}{g.pk}/", json.dumps(body), content_type="application/json")

    def test_cannot_add_a_mailbox_they_cannot_send_from(self):
        g = group("HR")
        resp = self.put(g, mailboxes=["hr"])
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(g.shared_mailboxes.exists())

    def test_can_add_a_mailbox_their_own_group_sends_from(self):
        mine = group("Mine", "manage_staff", "manage_blog", mailboxes=["hr"])
        self.manager.groups.add(mine)
        g = group("HR")
        self.assertEqual(self.put(g, mailboxes=["hr"]).status_code, 200)

    def test_cannot_add_people_to_a_group_granting_more_than_they_hold(self):
        cases = [(group("Senders", "send_campaigns"), ["send_campaigns"]),
                 (group("HR Mail", mailboxes=["hr"]), [])]
        for g, kept in cases:
            with self.subTest(group=g.name):
                resp = self.put(g, capabilities=kept, member_ids=[self.ann.pk])
                self.assertEqual(resp.status_code, 403)
                self.assertFalse(self.ann.groups.filter(pk=g.pk).exists())

    def test_cannot_invite_into_a_group_with_a_mailbox_they_cannot_send_from(self):
        g = group("HR Mail", mailboxes=["hr"])
        resp = self.client.post("/api/staff/invitations/", json.dumps(
            {"email": "new@example.com", "role_ids": [g.pk]}), content_type="application/json")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(StaffInvitation.objects.exists())

    def test_can_add_people_to_a_group_within_their_reach(self):
        g = group("Writers", "manage_blog")
        self.assertEqual(self.put(g, capabilities=["manage_blog"], member_ids=[self.ann.pk]).status_code, 200)
        self.assertTrue(self.ann.groups.filter(pk=g.pk).exists())

    def test_removing_people_is_never_restricted(self):
        g = group("Senders", "send_campaigns")
        self.ann.groups.add(g)
        resp = self.put(g, capabilities=["send_campaigns"], member_ids=[])
        # Keeping send_campaigns is not an addition, so only the removal is new.
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(self.ann.groups.filter(pk=g.pk).exists())

    def test_cannot_change_their_own_or_a_superusers_membership(self):
        g = group("Writers", "manage_blog")
        self.assertEqual(self.put(g, capabilities=["manage_blog"], member_ids=[self.manager.pk]).status_code, 403)
        boss = User.objects.create_superuser("boss", "b@example.com", "p")
        self.assertEqual(self.put(g, capabilities=["manage_blog"], member_ids=[boss.pk]).status_code, 403)
        mine = group("Mine")
        self.manager.groups.add(mine)
        self.assertEqual(self.put(mine, member_ids=[]).status_code, 403)
        self.assertTrue(self.manager.groups.filter(pk=mine.pk).exists())

    def test_a_refused_change_leaves_nothing_behind(self):
        g = group("Senders", "send_campaigns")
        self.put(g, name="Renamed", capabilities=["send_campaigns"], member_ids=[self.ann.pk])
        g.refresh_from_db()
        self.assertEqual(g.name, "Senders")
        self.assertFalse(AuditEntry.objects.exists())
