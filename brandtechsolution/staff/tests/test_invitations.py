import json
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.core import mail, signing
from django.test import TestCase
from django.utils import timezone

from staff.models import AuditEntry, StaffInvitation
from staff.tokens import make_invitation_token


def staff_with(*codenames, username="cap"):
    user = User.objects.create_user(username, password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class InvitationCreateTest(TestCase):
    def setUp(self):
        # Also holds the Editor role's capabilities: inviting someone with
        # that role below is a grant, and grants are only permitted for
        # capabilities the actor already has (see
        # InvitationGrantRestrictionTest). Mirrors the same fix in
        # test_people_api.py's RoleAssignmentTest.setUp.
        self.admin = staff_with(
            "manage_staff", "manage_blog", "publish_blog", "manage_projects",
            username="admin",
        )
        self.client.force_login(self.admin)
        self.editor = Group.objects.get(name="Editor")

    def _invite(self, email="new@example.com"):
        return self.client.post(
            "/api/staff/invitations/",
            json.dumps({"email": email, "role_ids": [self.editor.pk]}),
            content_type="application/json",
        )

    def test_requires_manage_staff(self):
        self.client.force_login(staff_with(username="nobody"))
        self.assertEqual(self._invite().status_code, 403)

    def test_creates_an_invitation_without_a_user(self):
        resp = self._invite()
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(StaffInvitation.objects.filter(email="new@example.com").exists())
        self.assertFalse(User.objects.filter(username="new@example.com").exists())

    def test_sends_an_email_containing_the_link(self):
        self._invite()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("new@example.com", mail.outbox[0].to)
        self.assertIn("/staff/invite/", mail.outbox[0].body)

    def test_email_is_lowercased(self):
        self._invite("MixedCase@Example.COM")
        self.assertTrue(
            StaffInvitation.objects.filter(email="mixedcase@example.com").exists()
        )

    def test_is_audited(self):
        self._invite()
        entry = AuditEntry.objects.get(action="invite_sent")
        self.assertEqual(entry.actor, self.admin)
        self.assertIn("new@example.com", entry.summary)

    def test_existing_account_is_refused(self):
        User.objects.create_user("taken@example.com", password="p", is_staff=True)
        resp = self._invite("taken@example.com")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already", json.dumps(resp.json()).lower())

    def test_duplicate_pending_invitation_is_refused(self):
        self._invite()
        self.assertEqual(self._invite().status_code, 400)


class InvitationGrantRestrictionTest(TestCase):
    """Inviting someone with roles is a grant: Task 10's rule that a
    non-superuser may only grant a role whose capabilities are a subset of
    their own must apply here too. Otherwise an administrator could invite a
    second address of their own carrying the Administrator role and accept
    that invitation themselves, trivially escalating."""

    def setUp(self):
        self.admin = staff_with("manage_staff", username="admin")
        self.client.force_login(self.admin)

    def _invite(self, group, email="new@example.com"):
        return self.client.post(
            "/api/staff/invitations/",
            json.dumps({"email": email, "role_ids": [group.pk]}),
            content_type="application/json",
        )

    def test_cannot_invite_with_a_role_carrying_capabilities_actor_lacks(self):
        marketing = Group.objects.get(name="Marketing")
        resp = self._invite(marketing)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(StaffInvitation.objects.filter(email="new@example.com").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_can_invite_with_a_role_whose_capabilities_actor_fully_holds(self):
        subset_role = Group.objects.create(name="Staff Viewer")
        subset_role.permissions.add(
            Permission.objects.get(
                codename="manage_staff", content_type__app_label="staff"
            )
        )
        resp = self._invite(subset_role)
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(StaffInvitation.objects.filter(email="new@example.com").exists())


class InvitationAcceptTest(TestCase):
    def setUp(self):
        self.editor = Group.objects.get(name="Editor")
        self.invitation = StaffInvitation.objects.create(
            email="new@example.com",
            invited_by=staff_with("manage_staff", username="admin"),
        )
        self.invitation.groups.add(self.editor)
        self.token = make_invitation_token(self.invitation.pk)

    def test_get_shows_the_form(self):
        resp = self.client.get(f"/staff/invite/{self.token}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "new@example.com")

    def test_post_creates_a_staff_user_with_the_roles(self):
        resp = self.client.post(
            f"/staff/invite/{self.token}/",
            {"password1": "a-good-password-42", "password2": "a-good-password-42"},
        )
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username="new@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("a-good-password-42"))
        self.assertEqual(list(user.groups.all()), [self.editor])

    def test_acceptance_is_recorded_and_audited(self):
        self.client.post(
            f"/staff/invite/{self.token}/",
            {"password1": "a-good-password-42", "password2": "a-good-password-42"},
        )
        self.invitation.refresh_from_db()
        self.assertIsNotNone(self.invitation.accepted_at)
        self.assertTrue(AuditEntry.objects.filter(action="invite_accepted").exists())

    def test_mismatched_passwords_are_rejected(self):
        resp = self.client.post(
            f"/staff/invite/{self.token}/",
            {"password1": "a-good-password-42", "password2": "different-42"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="new@example.com").exists())

    def test_a_token_cannot_be_used_twice(self):
        payload = {"password1": "a-good-password-42", "password2": "a-good-password-42"}
        self.client.post(f"/staff/invite/{self.token}/", payload)
        resp = self.client.post(f"/staff/invite/{self.token}/", payload)
        self.assertEqual(resp.status_code, 410)
        self.assertEqual(User.objects.filter(username="new@example.com").count(), 1)

    def test_a_revoked_invitation_rejects_its_token(self):
        self.invitation.delete()
        resp = self.client.get(f"/staff/invite/{self.token}/")
        self.assertEqual(resp.status_code, 410)

    def test_a_tampered_token_is_rejected(self):
        resp = self.client.get(f"/staff/invite/{self.token}xyz/")
        self.assertEqual(resp.status_code, 410)

    def test_an_expired_token_is_rejected(self):
        from staff import tokens

        stale = signing.dumps(
            {"id": self.invitation.pk}, salt=tokens.INVITATION_SALT
        )
        # max_age is measured from the signature timestamp. A negative max_age
        # expires any token deterministically, with no sleep and no dependence
        # on how many microseconds the test took.
        with self.settings(STAFF_INVITATION_MAX_AGE=-1):
            resp = self.client.get(f"/staff/invite/{stale}/")
        self.assertEqual(resp.status_code, 410)

    def test_a_valid_token_is_accepted_within_the_window(self):
        """Guards against the expiry check rejecting everything."""
        resp = self.client.get(f"/staff/invite/{self.token}/")
        self.assertEqual(resp.status_code, 200)


class InvitationRevokeTest(TestCase):
    def test_revoking_deletes_the_invitation_and_audits(self):
        admin = staff_with("manage_staff", username="admin")
        invitation = StaffInvitation.objects.create(
            email="new@example.com", invited_by=admin
        )
        self.client.force_login(admin)
        resp = self.client.delete(f"/api/staff/invitations/{invitation.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(StaffInvitation.objects.filter(pk=invitation.pk).exists())
        self.assertTrue(AuditEntry.objects.filter(action="invite_revoked").exists())


class InvitationResendTest(TestCase):
    def setUp(self):
        self.admin = staff_with("manage_staff", username="admin")
        self.invitation = StaffInvitation.objects.create(
            email="new@example.com", invited_by=self.admin
        )
        self.client.force_login(self.admin)

    def _resend(self, pk=None):
        return self.client.post(
            f"/api/staff/invitations/{pk or self.invitation.pk}/resend/"
        )

    def test_requires_manage_staff(self):
        self.client.force_login(staff_with(username="nobody"))
        self.assertEqual(self._resend().status_code, 403)

    def test_sends_a_working_link_and_audits(self):
        resp = self._resend()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(AuditEntry.objects.filter(action="invite_resent").exists())
        # The freshly minted token must actually open the form, not just be
        # well-formed: a resend that mails a dead link is the failure that
        # matters to the invitee.
        token = mail.outbox[0].body.split("/staff/invite/")[1].split("/")[0]
        self.assertContains(self.client.get(f"/staff/invite/{token}/"), "Set your password")

    def test_an_accepted_invitation_cannot_be_resent(self):
        # get_queryset() filters accepted invitations out, so this 404s.
        # Resending one would mail a link that mints a second account.
        self.invitation.accepted_at = timezone.now()
        self.invitation.save()
        self.assertEqual(self._resend().status_code, 404)
        self.assertEqual(len(mail.outbox), 0)


class AcceptanceCollisionTest(TestCase):
    """The invited address may be registered through the public /signup/
    page between the invitation being issued and being accepted."""

    def setUp(self):
        self.invitation = StaffInvitation.objects.create(email="new@example.com")
        self.token = make_invitation_token(self.invitation.pk)

    def _accept(self):
        return self.client.post(
            f"/staff/invite/{self.token}/",
            {"password1": "Sunfish-Bracket-41", "password2": "Sunfish-Bracket-41"},
        )

    def test_a_taken_username_is_refused_cleanly(self):
        # Previously an unhandled IntegrityError - a 500, not a 409.
        User.objects.create_user("new@example.com", password="x")
        self.assertEqual(self._accept().status_code, 409)

    def test_a_taken_email_on_another_username_is_refused(self):
        # Two accounts sharing one address would make password reset ambiguous.
        User.objects.create_user("someone", email="new@example.com", password="x")
        self.assertEqual(self._accept().status_code, 409)

    def test_a_refused_acceptance_does_not_burn_the_invitation(self):
        user = User.objects.create_user("new@example.com", password="x")
        self.assertEqual(self._accept().status_code, 409)
        self.invitation.refresh_from_db()
        self.assertIsNone(self.invitation.accepted_at)
        # Once the colliding account is gone the original link still works.
        user.delete()
        self.assertEqual(self._accept().status_code, 302)


class PasswordPolicyTest(TestCase):
    def setUp(self):
        self.invitation = StaffInvitation.objects.create(email="new@example.com")
        self.token = make_invitation_token(self.invitation.pk)

    def _accept(self, password):
        return self.client.post(
            f"/staff/invite/{self.token}/",
            {"password1": password, "password2": password},
        )

    def test_configured_validators_are_applied(self):
        # This is the only form in the codebase that mints is_staff accounts,
        # so AUTH_PASSWORD_VALIDATORS must not be bypassed here.
        for weak in ["1234567890", "password12", "new@example.com"]:
            with self.subTest(password=weak):
                self.assertEqual(self._accept(weak).status_code, 200)
                self.assertFalse(User.objects.filter(username=weak).exists())
        self.assertFalse(StaffInvitation.objects.get(pk=self.invitation.pk).accepted_at)

    def test_a_strong_password_is_accepted(self):
        self.assertEqual(self._accept("Sunfish-Bracket-41").status_code, 302)


class ReinviteAfterAcceptanceTest(TestCase):
    def test_an_accepted_address_can_be_invited_again(self):
        # Someone leaves, their account is deleted, they are re-hired. A plain
        # unique=True on email would block this permanently with no API path
        # to clear the stale row.
        admin = staff_with("manage_staff", username="admin")
        StaffInvitation.objects.create(
            email="alum@example.com", accepted_at=timezone.now()
        )
        self.client.force_login(admin)
        resp = self.client.post(
            "/api/staff/invitations/",
            json.dumps({"email": "alum@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_a_second_pending_invitation_is_still_refused(self):
        # DRF builds a condition-aware validator from Meta.constraints, so a
        # duplicate PENDING invitation is still a clean 400, not a 500.
        admin = staff_with("manage_staff", username="admin")
        StaffInvitation.objects.create(email="dup@example.com")
        self.client.force_login(admin)
        resp = self.client.post(
            "/api/staff/invitations/",
            json.dumps({"email": "dup@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already exists", str(resp.json()["email"]))


class ResendCollisionTest(TestCase):
    def test_resend_is_refused_once_the_address_is_taken(self):
        # Resending here would mail a link that can only ever 409.
        admin = staff_with("manage_staff", username="admin")
        invitation = StaffInvitation.objects.create(email="new@example.com")
        User.objects.create_user("new@example.com", password="x")
        self.client.force_login(admin)
        resp = self.client.post(f"/api/staff/invitations/{invitation.pk}/resend/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)


class ConcurrentAcceptanceTest(TestCase):
    """The guarded UPDATE, tested as the sole defence.

    test_a_token_cannot_be_used_twice is sequential: by the time the second
    request arrives, the pre-read at views.py already returns None and
    short-circuits to 410, so the guarded UPDATE is never reached and that
    test passes even with the guard removed. Here a competing acceptance
    lands *after* the pre-read - during password validation - so the guard
    is the only thing standing between one link and two accounts.
    """

    def test_a_second_acceptance_landing_mid_request_is_refused(self):
        invitation = StaffInvitation.objects.create(email="new@example.com")
        token = make_invitation_token(invitation.pk)

        def claim_it_first(*args, **kwargs):
            StaffInvitation.objects.filter(pk=invitation.pk).update(
                accepted_at=timezone.now()
            )
            User.objects.create_user("new@example.com", password="x", is_staff=True)

        with mock.patch("staff.views.validate_password", side_effect=claim_it_first):
            resp = self.client.post(
                f"/staff/invite/{token}/",
                {"password1": "Sunfish-Bracket-41", "password2": "Sunfish-Bracket-41"},
            )

        self.assertEqual(resp.status_code, 410)
        self.assertEqual(User.objects.filter(username="new@example.com").count(), 1)


class SendFailureTest(TestCase):
    """A mail-server problem must not surface as a 500, and must leave a
    record - otherwise an admin sees a crash and cannot tell whether the
    invitation went out."""

    def setUp(self):
        self.admin = staff_with("manage_staff", username="admin")
        self.client.force_login(self.admin)

    def test_create_survives_a_send_failure_and_audits_it(self):
        with mock.patch("staff.api.send_invitation", side_effect=RuntimeError("smtp")):
            resp = self.client.post(
                "/api/staff/invitations/",
                json.dumps({"email": "new@example.com"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 201)
        # The invitation survives so it can be resent once mail works.
        self.assertTrue(StaffInvitation.objects.filter(email="new@example.com").exists())
        self.assertTrue(AuditEntry.objects.filter(action="invite_send_failed").exists())

    def test_resend_reports_a_send_failure_instead_of_500ing(self):
        invitation = StaffInvitation.objects.create(email="new@example.com")
        with mock.patch("staff.api.send_invitation", side_effect=RuntimeError("smtp")):
            resp = self.client.post(f"/api/staff/invitations/{invitation.pk}/resend/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(AuditEntry.objects.filter(action="invite_send_failed").exists())
