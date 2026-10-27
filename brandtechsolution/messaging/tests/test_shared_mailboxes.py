import json

from django.contrib.auth.models import Group
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from messaging.models import MailThread, SharedMailbox
from staff.handles import validate_handle
from staff.models import AuditEntry

from .test_mail import admin, inbound, staff

API = "/api/messaging/mail"


def in_group(user, name, *mailboxes):
    group, _ = Group.objects.get_or_create(name=name)
    group.shared_mailboxes.add(*SharedMailbox.objects.filter(name__in=mailboxes))
    user.groups.add(group)
    return group


@override_settings(
    MAILBOX_DOMAIN="teklora.co.ke",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class SharedMailboxTest(TestCase):
    def setUp(self):
        self.hr = staff("hrperson")
        self.sales = staff("salesperson")
        in_group(self.hr, "HR", "hr", "careers")
        in_group(self.sales, "Sales", "sales")

    def boxes(self, user):
        self.client.force_login(user)
        return self.client.get(f"{API}/mailboxes/").json()["shared"]

    # --- the table replaces the hardcoded list ------------------------------

    def test_the_original_mailboxes_are_seeded(self):
        self.assertEqual(
            sorted(SharedMailbox.objects.values_list("name", flat=True)),
            ["billing", "careers", "contact", "hello", "hr", "info", "jobs", "sales", "support"],
        )

    def test_mail_to_a_new_mailbox_lands_in_it(self):
        SharedMailbox.objects.create(name="events")
        inbound(self.client, "events@teklora.co.ke")
        thread = MailThread.objects.get()
        self.assertEqual((thread.mailbox, thread.owner), ("events", None))

    def test_mail_to_an_unknown_name_still_lands_in_unmatched(self):
        inbound(self.client, "nobody@teklora.co.ke")
        self.assertEqual(MailThread.objects.get().mailbox, "other")

    # --- group access ---------------------------------------------------------

    def test_members_read_only_their_groups_mailboxes(self):
        inbound(self.client, "hr@teklora.co.ke", subject="Leave request")
        inbound(self.client, "sales@teklora.co.ke", subject="Big order")
        inbound(self.client, "nobody@teklora.co.ke", subject="Stray")

        self.assertEqual([b["mailbox"] for b in self.boxes(self.hr)], ["careers", "hr"])
        self.assertEqual(self.client.get(f"{API}/unread/").json()["unread"], 1)
        hr_thread = MailThread.objects.get(mailbox="hr")
        sales_thread = MailThread.objects.get(mailbox="sales")
        stray = MailThread.objects.get(mailbox="other")

        self.assertEqual(self.client.get(f"{API}/threads/{hr_thread.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"{API}/threads/{sales_thread.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"{API}/threads/{stray.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"{API}/threads/?box=sales").status_code, 403)
        self.assertEqual(self.client.get(f"{API}/threads/?box=other").status_code, 403)
        listed = self.client.get(f"{API}/threads/?box=hr").json()["results"]
        self.assertEqual([t["subject"] for t in listed], ["Leave request"])

    def test_members_reply_and_compose_from_their_groups_mailboxes(self):
        inbound(self.client, "hr@teklora.co.ke")
        thread = MailThread.objects.get()
        self.client.force_login(self.hr)
        resp = self.client.post(f"{API}/threads/{thread.id}/reply/", {"body": "On it."},
                                content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIn("hr@teklora.co.ke", mail.outbox[-1].from_email)

        resp = self.client.post(f"{API}/compose/", {
            "from": "careers", "to": "a@example.com", "subject": "Offer", "body": "Welcome."},
            content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = self.client.post(f"{API}/compose/", {
            "from": "sales", "to": "a@example.com", "subject": "Offer", "body": "Welcome."},
            content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_view_inbox_and_handle_inquiries_still_reach_every_mailbox(self):
        SharedMailbox.objects.create(name="events")
        reader = staff("reader", "view_inbox")
        names = [b["mailbox"] for b in self.boxes(reader)]
        self.assertEqual(names[-1], "other")
        self.assertIn("events", names)
        self.assertFalse(any(b["can_send"] for b in self.boxes(reader)))

        handler = staff("handler", "view_inbox", "handle_inquiries")
        sendable = [b["mailbox"] for b in self.boxes(handler) if b["can_send"]]
        self.assertIn("events", sendable)
        self.assertNotIn("other", sendable)

    def test_a_deactivated_member_loses_access(self):
        inbound(self.client, "hr@teklora.co.ke")
        thread = MailThread.objects.get()
        self.hr.is_active = False
        self.hr.save()
        self.client.force_login(self.hr)
        self.assertIn(self.client.get(f"{API}/threads/{thread.id}/").status_code, (403, 404))

    def test_group_members_are_emailed_about_their_mailboxes(self):
        self.hr.email = "hr.person@personal.example"
        self.hr.save()
        boss = admin("boss")
        inbound(self.client, "careers@teklora.co.ke", subject="Application")
        # One notification per person.
        recipients = {to for m in mail.outbox if "Application" in m.subject for to in m.to}
        self.assertIn("hr.person@personal.example", recipients)
        self.assertIn(boss.email, recipients)
        self.assertNotIn(self.sales.email, recipients)

    # --- managing mailboxes ---------------------------------------------------

    def test_creating_and_deleting_needs_manage_staff(self):
        self.client.force_login(self.hr)
        self.assertEqual(self.client.get(f"{API}/shared/").status_code, 403)
        self.assertEqual(self.client.post(f"{API}/shared/", {"name": "events"}).status_code, 403)
        self.assertEqual(self.client.delete(f"{API}/shared/hr/").status_code, 403)

    def test_create_validates_the_name_and_is_audited(self):
        manager = staff("manager", "manage_staff")
        self.client.force_login(manager)
        resp = self.client.post(f"{API}/shared/", {"name": " Events@teklora.co.ke "})
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["address"], "events@teklora.co.ke")
        self.assertTrue(AuditEntry.objects.filter(action="mailbox_created").exists())
        for bad in ("events", "postmaster", "other", "hrperson", "a", "no spaces", "x..y"):
            with self.subTest(name=bad):
                self.assertEqual(self.client.post(f"{API}/shared/", {"name": bad}).status_code, 400)

    def test_listing_shows_groups_and_thread_counts(self):
        inbound(self.client, "hr@teklora.co.ke")
        self.client.force_login(staff("manager", "manage_staff"))
        rows = {r["name"]: r for r in self.client.get(f"{API}/shared/").json()}
        self.assertEqual(rows["hr"]["groups"], ["HR"])
        self.assertEqual(rows["hr"]["threads"], 1)
        self.assertEqual(rows["info"]["groups"], [])

    def test_deleting_moves_its_mail_to_unmatched(self):
        inbound(self.client, "hr@teklora.co.ke")
        self.client.force_login(staff("manager", "manage_staff"))
        self.assertEqual(self.client.delete(f"{API}/shared/hr/").status_code, 204)
        self.assertFalse(SharedMailbox.objects.filter(name="hr").exists())
        self.assertEqual(MailThread.objects.get().mailbox, "other")
        entry = AuditEntry.objects.get(action="mailbox_deleted")
        self.assertEqual(entry.detail["groups"], ["HR"])
        inbound(self.client, "hr@teklora.co.ke", subject="After")
        self.assertEqual(MailThread.objects.get(subject="After").mailbox, "other")

    def test_nobody_can_take_a_shared_mailbox_as_their_handle(self):
        SharedMailbox.objects.create(name="events")
        with self.assertRaises(ValidationError):
            validate_handle("events")

    def test_campaigns_can_be_sent_from_a_new_mailbox(self):
        SharedMailbox.objects.create(name="events")
        self.client.force_login(staff("marketer", "manage_campaigns"))
        senders = self.client.get("/api/messaging/campaigns/overview/").json()["senders"]
        self.assertIn("events", [s["value"] for s in senders])


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class RoleMailboxApiTest(TestCase):
    def test_role_api_reads_and_writes_mailboxes(self):
        self.client.force_login(admin("boss"))
        resp = self.client.post("/api/staff/roles/", json.dumps(
            {"name": "Recruiting", "capabilities": [], "mailboxes": ["careers", "jobs"]}),
            content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["mailboxes"], ["careers", "jobs"])
        resp = self.client.post("/api/staff/roles/", json.dumps(
            {"name": "Bad", "capabilities": [], "mailboxes": ["nope"]}),
            content_type="application/json")
        self.assertEqual(resp.status_code, 400)
