"""Invite the founding team onto the platform, once each.

Notifications used to be addressed to a list of email addresses hardcoded in
two view modules. That made the team roster a deploy artefact: somebody leaving
kept receiving customer names and phone numbers until a developer edited Python,
and somebody joining received nothing until the same happened. It is also how
one mistyped address survived in both copies for months.

Now every notification is addressed to whoever holds the relevant capability,
and the seed list exists only to get those people onto the platform in the first
place. After that the panel is the single record of who is on the team.

Run from entrypoint.sh's `web` role, immediately after migrate, and safe to run
by hand at any time.

Why a command and not AppConfig.ready():
ready() executes in every process that loads Django -- all three gunicorn
workers, the Celery worker, beat, and every manage.py invocation including
migrate and collectstatic. Seeding there would send the same invitation five
times on one deployment, run against a database that migrate has not finished
preparing, and put a network call in the boot path of every process. The web
role already runs migrate and collectstatic exactly once; this belongs beside
them.
"""
import logging

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from staff.emails import send_invitation
from staff.models import StaffInvitation
from staff.tokens import DEFAULT_MAX_AGE

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send a panel invitation to any seed team address without an account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or writing anything.",
        )

    def _say(self, message):
        """Respect --verbosity 0, which the test suite and the outbox cron use."""
        if self.verbosity:
            self.stdout.write(message)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        self.verbosity = options.get("verbosity", 1)
        emails = getattr(settings, "TEAM_SEED_EMAILS", [])
        if not emails:
            self._say("No TEAM_SEED_EMAILS configured; nothing to do.")
            return

        group = self._seed_group()
        # Token lifetime: a pending invitation older than this can no longer be
        # accepted, so reissuing it is the only way its holder ever gets in.
        # Anything younger is still live and must not be mailed again -- that is
        # what stops a deployment resending on every boot.
        max_age = getattr(settings, "STAFF_INVITATION_MAX_AGE", DEFAULT_MAX_AGE)
        expiry_cutoff = timezone.now() - timezone.timedelta(seconds=max_age)

        counts = {"has_account": 0, "still_valid": 0, "sent": 0, "failed": 0}

        for email in emails:
            outcome = self._process(email, group, expiry_cutoff, dry_run)
            counts[outcome] += 1

        self._say(
            "Team seed: {sent} invitation(s) sent, {has_account} already have an "
            "account, {still_valid} have a live invitation, {failed} failed.".format(
                **counts
            )
        )
        self._report_coverage()

    def _report_coverage(self):
        """Say who would actually receive each notification, right now.

        Invitations are only half the job: the addresses are resolved from
        capabilities at send time, and an account with no email address is
        skipped silently. createsuperuser treats email as optional, so the most
        likely way to end a deployment with nobody reachable is a superuser
        created without one -- and that failure is otherwise invisible until a
        customer inquiry goes unanswered.
        """
        from staff.emails import capability_holder_emails

        uncovered = []
        for label, codename in (
            ("contact inquiries", "handle_inquiries"),
            ("bookings", "manage_appointments"),
            ("task reviews", "manage_tasks"),
            ("editorial reviews", "publish_blog"),
        ):
            holders = capability_holder_emails(codename)
            if holders:
                self._say(f"  {label}: {len(holders)} recipient(s)")
            else:
                uncovered.append(f"{label} ({codename})")

        if uncovered:
            self.stderr.write(
                "WARNING: nobody with an email address can receive: "
                + ", ".join(uncovered)
                + ". Check that staff accounts -- including superusers, for "
                "whom createsuperuser makes email optional -- have an address set."
            )

    def _seed_group(self):
        """The preset role a seeded invitation carries.

        Missing rather than absent is worth saying out loud: the invitation is
        still issued, but the person lands with no capabilities and receives
        none of the notifications this exists to deliver.
        """
        name = getattr(settings, "TEAM_SEED_ROLE", "")
        if not name:
            return None
        group = Group.objects.filter(name=name).first()
        if group is None:
            self.stderr.write(
                f"Preset role {name!r} does not exist; invitations will carry "
                "no capabilities."
            )
        return group

    def _process(self, email, group, expiry_cutoff, dry_run):
        # Matches the resend endpoint's check: the public /signup/ page stores
        # the address as the username, so an account can exist under either
        # field and an invitation to it would only dead-end.
        if User.objects.filter(
            Q(username__iexact=email) | Q(email__iexact=email)
        ).exists():
            return "has_account"

        invitation = StaffInvitation.objects.filter(
            email__iexact=email, accepted_at__isnull=True
        ).first()

        if invitation is not None:
            # last_sent_at is null for invitations predating that field; fall
            # back to created_at, which is when they were sent.
            sent_at = invitation.last_sent_at or invitation.created_at
            if sent_at > expiry_cutoff:
                return "still_valid"
        elif not dry_run:
            # Reuses the pending row when one exists rather than creating a
            # second: the partial unique constraint forbids two pending
            # invitations for one address.
            invitation = StaffInvitation.objects.create(email=email)
            if group is not None:
                invitation.groups.add(group)

        if dry_run:
            self._say(f"would invite {email}")
            return "sent"

        try:
            send_invitation(invitation)
        except Exception:
            # One unreachable address must not stop the rest of the team being
            # invited, and must not fail the deployment this runs inside.
            logger.exception("Could not send team invitation to %s", email)
            self.stderr.write(f"failed to invite {email}")
            return "failed"

        self._say(f"invited {email}")
        return "sent"
