from django.contrib.auth.models import Group, User
from django.test import TestCase

from staff.audit import record
from staff.models import AuditEntry


class AuditRecordTest(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user("actor", password="p", is_staff=True)
        self.target = User.objects.create_user("target", password="p", is_staff=True)
        self.group = Group.objects.get(name="Editor")

    def test_record_writes_an_entry(self):
        entry = record(
            actor=self.actor,
            action="roles_changed",
            summary="actor changed target's roles to Editor",
            target_user=self.target,
        )
        self.assertEqual(AuditEntry.objects.count(), 1)
        self.assertEqual(entry.actor, self.actor)
        self.assertEqual(entry.action, "roles_changed")

    def test_summary_survives_target_deletion(self):
        """The summary is rendered at write time, so it stays readable."""
        record(
            actor=self.actor,
            action="group_deleted",
            summary="actor deleted the role Editor",
            target_group=self.group,
        )
        self.group.delete()
        entry = AuditEntry.objects.get()
        self.assertEqual(entry.summary, "actor deleted the role Editor")
        self.assertIsNone(entry.target_group)

    def test_actor_deletion_keeps_the_entry(self):
        record(actor=self.actor, action="invite_sent", summary="actor invited x@y.com")
        self.actor.delete()
        entry = AuditEntry.objects.get()
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.summary, "actor invited x@y.com")

    def test_detail_holds_before_and_after(self):
        entry = record(
            actor=self.actor,
            action="group_updated",
            summary="actor changed the Editor role",
            target_group=self.group,
            detail={"before": ["manage_blog"], "after": ["manage_blog", "publish_blog"]},
        )
        entry.refresh_from_db()
        self.assertEqual(entry.detail["after"], ["manage_blog", "publish_blog"])

    def test_entries_are_newest_first(self):
        record(actor=self.actor, action="invite_sent", summary="first")
        record(actor=self.actor, action="invite_sent", summary="second")
        self.assertEqual(
            list(AuditEntry.objects.values_list("summary", flat=True)),
            ["second", "first"],
        )
