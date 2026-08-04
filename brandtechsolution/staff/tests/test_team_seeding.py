"""The seed list invites people once; the panel owns the roster afterwards.

The property that matters is idempotence. This runs on every deployment of the
web container, so anything that resends on a second run would mail the whole
team on every release.
"""
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from staff.models import StaffInvitation
from staff.tokens import DEFAULT_MAX_AGE

SEED = ["one@example.com", "two@example.com"]


@override_settings(TEAM_SEED_EMAILS=SEED, TEAM_SEED_ROLE="Support")
class SeedTeamInvitationsTest(TestCase):
    def seed(self, **kwargs):
        call_command("seed_team_invitations", verbosity=0, **kwargs)

    def test_a_first_run_invites_everyone(self):
        self.seed()

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), sorted(SEED)
        )
        self.assertEqual(StaffInvitation.objects.count(), 2)

    def test_a_second_run_sends_nothing(self):
        """Idempotence. This runs on every deployment."""
        self.seed()
        mail.outbox.clear()

        self.seed()

        self.assertEqual(mail.outbox, [])
        self.assertEqual(StaffInvitation.objects.count(), 2)

    def test_an_address_with_an_account_is_skipped(self):
        User.objects.create_user("one@example.com", "one@example.com", "pw")

        self.seed()

        self.assertEqual([m.to[0] for m in mail.outbox], ["two@example.com"])

    def test_an_account_registered_under_username_only_is_skipped(self):
        """The public signup page stores the address as the username, and an
        invitation to it would dead-end -- the same check the resend endpoint
        makes."""
        User.objects.create_user("one@example.com", "", "pw")

        self.seed()

        self.assertEqual([m.to[0] for m in mail.outbox], ["two@example.com"])

    def test_an_expired_invitation_is_reissued(self):
        """A pending invitation past the token lifetime can never be accepted,
        so leaving it alone would strand that person permanently."""
        self.seed()
        mail.outbox.clear()
        StaffInvitation.objects.filter(email="one@example.com").update(
            last_sent_at=timezone.now() - timezone.timedelta(
                seconds=DEFAULT_MAX_AGE + 60
            )
        )

        self.seed()

        self.assertEqual([m.to[0] for m in mail.outbox], ["one@example.com"])
        # Reused, not duplicated: the partial unique constraint forbids two
        # pending invitations for one address.
        self.assertEqual(
            StaffInvitation.objects.filter(email="one@example.com").count(), 1
        )

    def test_an_accepted_invitation_is_not_reissued(self):
        self.seed()
        mail.outbox.clear()
        invitation = StaffInvitation.objects.get(email="one@example.com")
        invitation.accepted_at = timezone.now()
        invitation.save()
        User.objects.create_user("one", "one@example.com", "pw")

        self.seed()

        self.assertEqual(mail.outbox, [])

    def test_the_invitation_carries_the_preset_role(self):
        self.seed()

        invitation = StaffInvitation.objects.get(email="one@example.com")
        self.assertEqual(
            list(invitation.groups.values_list("name", flat=True)), ["Support"]
        )

    def test_one_unreachable_address_does_not_block_the_rest(self):
        real_send = mail.get_connection

        def explode_on_first(invitation, request=None):
            if invitation.email == "one@example.com":
                raise RuntimeError("mailbox full")
            return real_send

        with mock.patch(
            "staff.management.commands.seed_team_invitations.send_invitation",
            side_effect=explode_on_first,
        ) as sender:
            self.seed()

        self.assertEqual(
            sorted(c.args[0].email for c in sender.call_args_list), sorted(SEED)
        )

    def test_a_failed_send_leaves_the_invitation_unsent_so_it_retries(self):
        with mock.patch(
            "staff.management.commands.seed_team_invitations.send_invitation",
            side_effect=RuntimeError("smtp"),
        ):
            self.seed()

        self.assertTrue(
            all(
                i.last_sent_at is None
                for i in StaffInvitation.objects.all()
            )
        )

    def test_dry_run_writes_nothing_and_sends_nothing(self):
        self.seed(dry_run=True)

        self.assertEqual(mail.outbox, [])
        self.assertEqual(StaffInvitation.objects.count(), 0)

    @override_settings(TEAM_SEED_EMAILS=[])
    def test_an_empty_seed_list_is_a_no_op(self):
        self.seed()

        self.assertEqual(mail.outbox, [])

    @override_settings(TEAM_SEED_ROLE="Nonexistent")
    def test_a_missing_preset_role_still_invites(self):
        """Better to get them onto the platform with no capabilities than to
        leave them off it entirely; the panel can grant roles afterwards."""
        self.seed()

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            StaffInvitation.objects.get(email="one@example.com").groups.count(), 0
        )


@override_settings(TEAM_SEED_EMAILS=SEED, TEAM_SEED_ROLE="Support")
class SeededAccountReceivesNotificationsTest(TestCase):
    """The point of the exercise: accepting an invitation is what enrols
    someone into the notifications, with no code change."""

    def test_accepting_a_seeded_invitation_earns_the_contact_notifications(self):
        from staff.emails import capability_holder_emails

        call_command("seed_team_invitations", verbosity=0)
        self.assertEqual(capability_holder_emails("handle_inquiries"), [])

        # What accept_invitation does: create the user and apply the roles.
        invitation = StaffInvitation.objects.get(email="one@example.com")
        user = User.objects.create_user(
            "one@example.com", "one@example.com", "pw", is_staff=True
        )
        user.groups.set(invitation.groups.all())

        self.assertEqual(
            capability_holder_emails("handle_inquiries"), ["one@example.com"]
        )
        self.assertEqual(
            capability_holder_emails("manage_appointments"), ["one@example.com"]
        )

    def test_someone_who_never_accepts_is_never_notified(self):
        from staff.emails import capability_holder_emails

        call_command("seed_team_invitations", verbosity=0)

        self.assertEqual(capability_holder_emails("handle_inquiries"), [])
        self.assertEqual(capability_holder_emails("manage_appointments"), [])


@override_settings(TEAM_SEED_EMAILS=SEED, TEAM_SEED_ROLE="Support")
class CoverageReportTest(TestCase):
    """Deploy-time warning that nobody can receive a notification.

    createsuperuser makes email optional, so a production superuser without an
    address holds every capability and receives nothing -- invisible until a
    customer inquiry goes unanswered.
    """

    def _run(self):
        from io import StringIO

        err = StringIO()
        call_command("seed_team_invitations", verbosity=0, stderr=err)
        return err.getvalue()

    def test_a_superuser_without_an_address_is_reported_as_uncovered(self):
        User.objects.create_superuser("root", "", "pw")

        self.assertIn("nobody with an email address can receive", self._run())

    def test_a_superuser_with_an_address_covers_every_notification(self):
        User.objects.create_superuser("root", "root@example.com", "pw")

        self.assertEqual(self._run(), "")

    def test_the_warning_names_the_capability_to_fix(self):
        self.assertIn("handle_inquiries", self._run())


class SupportRoleCoversTheLeadNotificationsTest(TestCase):
    def test_the_seeded_role_holds_both_notification_capabilities(self):
        """If this drifts, seeded members land without the notifications the
        whole exercise exists to deliver."""
        held = set(
            Group.objects.get(name="Support").permissions.values_list(
                "codename", flat=True
            )
        )
        self.assertIn("handle_inquiries", held)
        self.assertIn("manage_appointments", held)
