"""Mail access follows capabilities: view_inbox, handle_inquiries, view_all_mail."""
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.utils import timezone

from messaging import mailbox as mb
from messaging.models import MailThread


def grant(user, *codenames):
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="staff", codename__in=codenames
        )
    )
    return User.objects.get(pk=user.pk)  # drop the permission cache


class MailCapabilityTests(TestCase):
    def setUp(self):
        self.person = User.objects.create_user("p", "p@x.com", "pw", is_staff=True)
        self.colleague = User.objects.create_user("c", "c@x.com", "pw", is_staff=True)
        self.shared = MailThread.objects.create(owner=None, mailbox="info", subject="s", last_message_at=timezone.now())
        self.private = MailThread.objects.create(owner=self.colleague, mailbox="c", subject="x", last_message_at=timezone.now())

    def test_default_sees_neither(self):
        self.assertFalse(mb.can_read(self.person, self.shared))
        self.assertFalse(mb.can_read(self.person, self.private))

    def test_view_inbox_reads_shared_only(self):
        u = grant(self.person, "view_inbox")
        self.assertTrue(mb.can_read(u, self.shared))
        self.assertFalse(mb.can_read(u, self.private))
        self.assertFalse(mb.can_act(u, self.shared))

    def test_handle_inquiries_acts_on_shared(self):
        u = grant(self.person, "handle_inquiries")
        self.assertTrue(mb.can_act(u, self.shared))

    def test_view_all_mail_reads_but_cannot_act_on_personal(self):
        u = grant(self.person, "view_all_mail")
        self.assertTrue(mb.can_read(u, self.private))
        self.assertFalse(mb.can_act(u, self.private))


class SharedMailboxRoutingTests(TestCase):
    def test_careers_is_a_shared_mailbox_not_unmatched(self):
        self.assertEqual(mb.resolve_mailbox("careers"), ("careers", None))

    def test_an_unknown_name_is_still_unmatched(self):
        self.assertEqual(mb.resolve_mailbox("nobody-here"), (mb.OTHER, None))
