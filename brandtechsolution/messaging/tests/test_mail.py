from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from messaging.models import BlockedSender, Inquiry, MailMessage, MailSettings, MailThread
from staff.models import AuditEntry, StaffProfile

WEBHOOK = "/messaging/inbound-webhook/"


def staff(username, *codenames, **extra):
    user = User.objects.create_user(username, email=f"{username}@personal.example",
                                    is_staff=True, **extra)
    if codenames:
        user.user_permissions.add(*Permission.objects.filter(
            codename__in=codenames, content_type__app_label="staff"))
    return user


def inbound(client, recipient, subject="Hello", **extra):
    payload = {
        "from": "Client Person <client@example.com>",
        "sender": "client@example.com",
        "recipient": recipient,
        "To": recipient,
        "subject": subject,
        "body-plain": "Hi there,\nA question.\n\nOn Mon, someone wrote:\n> old stuff",
        "stripped-text": "Hi there,\nA question.",
        "timestamp": "1722898000",
        "token": "t",
        "signature": "s",
    }
    payload.update(extra)
    return client.post(WEBHOOK, payload)


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class InboundRoutingTest(TestCase):
    def setUp(self):
        self.ann = staff("ann")
        self.bob = staff("bob")

    def test_mail_to_a_handle_lands_only_in_that_mailbox(self):
        resp = inbound(self.client, "Ann@teklora.co.ke")
        self.assertEqual(resp.status_code, 200)
        thread = MailThread.objects.get()
        self.assertEqual((thread.mailbox, thread.owner), ("ann", self.ann))
        self.assertTrue(thread.unread)
        self.assertEqual(thread.counterpart_name, "Client Person")
        self.assertEqual(thread.snippet, "Hi there, A question.")
        # Personal mail is not an inquiry and notifies nobody.
        self.assertFalse(Inquiry.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_to_two_people_gives_each_their_own_copy(self):
        inbound(self.client, "ann@teklora.co.ke, bob@teklora.co.ke")
        self.assertEqual(
            sorted(MailThread.objects.values_list("mailbox", flat=True)), ["ann", "bob"]
        )

    def test_shared_and_unknown_addresses_are_shared_and_become_inquiries(self):
        inbound(self.client, "info@teklora.co.ke")
        inbound(self.client, "nobody-here@teklora.co.ke", subject="Lost")
        self.assertEqual(
            sorted(MailThread.objects.values_list("mailbox", flat=True)), ["info", "other"]
        )
        self.assertTrue(MailThread.objects.filter(owner__isnull=True).count() == 2)
        self.assertEqual(Inquiry.objects.count(), 2)

    def test_a_retried_webhook_is_not_filed_twice(self):
        inbound(self.client, "ann@teklora.co.ke", **{"Message-Id": "<abc@example.com>"})
        inbound(self.client, "ann@teklora.co.ke", **{"Message-Id": "<abc@example.com>"})
        self.assertEqual(MailMessage.objects.count(), 1)

    def test_a_reply_joins_its_thread(self):
        inbound(self.client, "ann@teklora.co.ke", **{"Message-Id": "<one@example.com>"})
        inbound(self.client, "ann@teklora.co.ke", subject="Re: Hello",
                **{"Message-Id": "<two@example.com>", "In-Reply-To": "<one@example.com>"})
        thread = MailThread.objects.get()
        self.assertEqual(thread.messages.count(), 2)

    def test_mail_to_an_unclaimed_handle_moves_to_whoever_claims_it(self):
        inbound(self.client, "carol@teklora.co.ke")
        self.assertEqual(MailThread.objects.get().mailbox, "other")
        carol = User.objects.create_user("carol@personal.example", email="carol@personal.example",
                                         password="x", is_staff=True)
        self.client.force_login(carol)
        self.client.post("/staff/address/", {"handle": "carol"})
        thread = MailThread.objects.get()
        self.assertEqual((thread.mailbox, thread.owner_id), ("carol", carol.pk))

    def test_contact_form_lands_in_info(self):
        with mock.patch("brandtechsolution.turnstile.passed", return_value=True):
            self.client.post(reverse("contact_submit"), {
                "name": "Jane", "email": "jane@example.com", "phone": "0712345678",
                "message": "Need a website",
            })
        thread = MailThread.objects.get()
        self.assertEqual((thread.mailbox, thread.owner), ("info", None))
        self.assertIn("0712345678", thread.messages.get().body_text)


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class MailAccessTest(TestCase):
    def setUp(self):
        self.ann = staff("ann")
        self.bob = staff("bob")
        self.support = staff("sue", "view_inbox")
        self.boss = staff("boss", "view_all_mail")
        inbound(self.client, "ann@teklora.co.ke")
        inbound(self.client, "info@teklora.co.ke")
        self.ann_thread = MailThread.objects.get(mailbox="ann")
        self.info_thread = MailThread.objects.get(mailbox="info")

    def ids(self, user, box):
        self.client.force_login(user)
        resp = self.client.get(f"/api/messaging/mail/threads/?box={box}")
        return resp.status_code, [t["id"] for t in resp.json().get("results", [])]

    def test_people_see_only_their_own_mailbox(self):
        self.assertEqual(self.ids(self.ann, "me"), (200, [self.ann_thread.id]))
        self.assertEqual(self.ids(self.bob, "me"), (200, []))
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(f"/api/messaging/mail/threads/{self.ann_thread.id}/").status_code, 404
        )

    def test_shared_mailboxes_need_view_inbox(self):
        self.assertEqual(self.ids(self.ann, "info")[0], 403)
        self.assertEqual(self.ids(self.support, "info"), (200, [self.info_thread.id]))

    def test_all_mail_needs_view_all_mail(self):
        self.assertEqual(self.ids(self.support, "all")[0], 403)
        status, ids = self.ids(self.boss, "all")
        self.assertEqual(status, 200)
        self.assertCountEqual(ids, [self.ann_thread.id, self.info_thread.id])

    def test_oversight_is_read_only_and_leaves_it_unread(self):
        self.client.force_login(self.boss)
        detail = self.client.get(f"/api/messaging/mail/threads/{self.ann_thread.id}/").json()
        self.assertFalse(detail["can_act"])
        self.ann_thread.refresh_from_db()
        self.assertTrue(self.ann_thread.unread)
        resp = self.client.post(
            f"/api/messaging/mail/threads/{self.ann_thread.id}/reply/",
            {"body": "hi"}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_owner_opening_marks_read_and_can_archive(self):
        self.client.force_login(self.ann)
        self.client.get(f"/api/messaging/mail/threads/{self.ann_thread.id}/")
        self.ann_thread.refresh_from_db()
        self.assertFalse(self.ann_thread.unread)
        self.client.post(f"/api/messaging/mail/threads/{self.ann_thread.id}/state/",
                         {"archived": True}, content_type="application/json")
        self.assertEqual(self.ids(self.ann, "me"), (200, []))
        self.client.force_login(self.ann)
        resp = self.client.get("/api/messaging/mail/threads/?box=me&archived=1")
        self.assertEqual([t["id"] for t in resp.json()["results"]], [self.ann_thread.id])

    def test_mailboxes_lists_what_each_person_gets(self):
        self.client.force_login(self.ann)
        data = self.client.get("/api/messaging/mail/mailboxes/").json()
        self.assertEqual(data["me"]["address"], "ann@teklora.co.ke")
        self.assertEqual(data["me"]["unread"], 1)
        self.assertEqual(data["shared"], [])
        self.assertFalse(data["all_mail"])

    def test_no_mailbox_before_a_handle_is_chosen(self):
        pending = User.objects.create_user("new@personal.example", is_staff=True)
        self.client.force_login(pending)
        self.assertIsNone(self.client.get("/api/messaging/mail/mailboxes/").json()["me"])


@override_settings(
    MAILBOX_DOMAIN="teklora.co.ke",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class SendingTest(TestCase):
    def setUp(self):
        self.ann = staff("ann", first_name="Ann", last_name="Wanjiru")
        inbound(self.client, "ann@teklora.co.ke", **{"Message-Id": "<orig@example.com>"})
        mail.outbox.clear()
        self.thread = MailThread.objects.get()
        self.client.force_login(self.ann)

    def test_reply_goes_from_the_owners_address_and_threads(self):
        resp = self.client.post(
            f"/api/messaging/mail/threads/{self.thread.id}/reply/",
            {"body": "Thanks, on it."}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        sent = mail.outbox[0]
        self.assertEqual(sent.from_email, "Ann Wanjiru <ann@teklora.co.ke>")
        self.assertEqual(sent.to, ["client@example.com"])
        self.assertEqual(sent.subject, "Re: Hello")
        self.assertEqual(sent.extra_headers["In-Reply-To"], "<orig@example.com>")
        self.assertEqual(self.thread.messages.filter(direction="out").count(), 1)

        # The client's answer to our reply joins the same thread.
        our_id = self.thread.messages.get(direction="out").message_id
        self.client.logout()
        inbound(self.client, "ann@teklora.co.ke", subject="Re: Hello",
                **{"Message-Id": "<answer@example.com>", "References": f"<orig@example.com> <{our_id}>"})
        self.assertEqual(MailThread.objects.count(), 1)
        self.assertEqual(self.thread.messages.count(), 3)

    def test_compose_from_own_address_shows_in_sent(self):
        resp = self.client.post("/api/messaging/mail/compose/", {
            "from": "me", "to": "someone@example.com, Other <other@example.com>",
            "subject": "Proposal", "body": "Attached is nothing.",
        }, content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(mail.outbox[0].to, ["someone@example.com", "Other <other@example.com>"])
        sent = self.client.get("/api/messaging/mail/threads/?box=sent").json()["results"]
        self.assertEqual([t["subject"] for t in sent], ["Proposal"])

    def test_compose_rejects_bad_addresses_and_shared_without_capability(self):
        bad = self.client.post("/api/messaging/mail/compose/", {
            "to": "not an address", "subject": "x", "body": "y"},
            content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        shared = self.client.post("/api/messaging/mail/compose/", {
            "from": "info", "to": "a@example.com", "subject": "x", "body": "y"},
            content_type="application/json")
        self.assertEqual(shared.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_provider_failure_records_nothing(self):
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=RuntimeError("down")):
            resp = self.client.post(
                f"/api/messaging/mail/threads/{self.thread.id}/reply/",
                {"body": "hello"}, content_type="application/json",
            )
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(self.thread.messages.filter(direction="out").exists())


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class SpamAndDeleteTest(TestCase):
    def setUp(self):
        self.ann = staff("ann")
        self.support = staff("sue", "view_inbox", "handle_inquiries")
        self.boss = staff("boss", "view_all_mail")
        inbound(self.client, "ann@teklora.co.ke")
        self.thread = MailThread.objects.get()

    def act(self, user, path, data=None):
        self.client.force_login(user)
        return self.client.post(
            f"/api/messaging/mail/threads/{self.thread.id}/{path}/",
            data or {}, content_type="application/json",
        )

    def listing(self, user, query):
        self.client.force_login(user)
        return [t["id"] for t in self.client.get(
            f"/api/messaging/mail/threads/?{query}").json()["results"]]

    def test_spam_moves_the_thread_and_blocks_the_sender(self):
        self.assertEqual(self.act(self.ann, "state", {"spam": True}).status_code, 200)
        self.assertEqual(self.listing(self.ann, "box=me"), [])
        self.assertEqual(self.listing(self.ann, "box=me&spam=1"), [self.thread.id])
        self.assertTrue(BlockedSender.is_blocked("CLIENT@example.com"))

        # The next email from them is filed as spam and raises nothing.
        self.client.logout()
        inbound(self.client, "info@teklora.co.ke", subject="Buy now")
        info = MailThread.objects.get(mailbox="info")
        self.assertTrue(info.spam)
        self.assertFalse(Inquiry.objects.exists())

    def test_not_spam_unblocks(self):
        self.act(self.ann, "state", {"spam": True})
        self.act(self.ann, "state", {"spam": False})
        self.assertFalse(BlockedSender.objects.exists())
        self.assertEqual(self.listing(self.ann, "box=me"), [self.thread.id])

    def test_blocked_contact_form_submissions_are_dropped_quietly(self):
        BlockedSender.objects.create(email="spammer@example.com")
        with mock.patch("brandtechsolution.turnstile.passed", return_value=True):
            resp = self.client.post(reverse("contact_submit"), {
                "name": "Web Master", "email": "Spammer@example.com", "message": "Monetag!",
            }, HTTP_ACCEPT="application/json")
        self.assertEqual(resp.json(), {"ok": True})
        self.assertFalse(Inquiry.objects.exists())
        self.assertFalse(MailThread.objects.filter(mailbox="info").exists())

    def test_colleagues_are_never_blocked(self):
        self.thread.counterpart_email = "bob@teklora.co.ke"
        self.thread.save()
        self.act(self.ann, "state", {"spam": True})
        self.assertFalse(BlockedSender.objects.exists())

    def test_delete_hides_it_from_the_owner_but_not_oversight(self):
        self.assertEqual(self.act(self.ann, "delete").status_code, 204)
        self.assertEqual(self.listing(self.ann, "box=me"), [])
        self.assertEqual(self.listing(self.ann, "box=me&archived=1"), [])
        self.client.force_login(self.ann)
        self.assertEqual(
            self.client.get(f"/api/messaging/mail/threads/{self.thread.id}/").status_code, 404
        )
        self.client.force_login(self.ann)
        self.assertEqual(self.client.get("/api/messaging/mail/mailboxes/").json()["me"]["unread"], 0)

        self.assertEqual(self.listing(self.boss, "box=all"), [self.thread.id])
        self.client.force_login(self.boss)
        detail = self.client.get(f"/api/messaging/mail/threads/{self.thread.id}/").json()
        self.assertTrue(detail["deleted"])
        self.assertFalse(detail["can_act"])

    def test_only_the_owner_can_delete_or_mark_spam(self):
        self.assertEqual(self.act(self.boss, "delete").status_code, 403)
        self.assertEqual(self.act(self.boss, "state", {"spam": True}).status_code, 403)
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.deleted_at)
        self.assertFalse(self.thread.spam)

    def test_a_new_reply_brings_a_deleted_thread_back(self):
        MailMessage.objects.filter(thread=self.thread).update(message_id="first@example.com")
        self.act(self.ann, "delete")
        self.client.logout()
        inbound(self.client, "ann@teklora.co.ke", subject="Re: Hello",
                **{"Message-Id": "<second@example.com>", "In-Reply-To": "<first@example.com>"})
        self.assertEqual(self.listing(self.ann, "box=me"), [self.thread.id])


@override_settings(
    MAILBOX_DOMAIN="teklora.co.ke",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class SendingLimitTest(TestCase):
    def setUp(self):
        self.ann = staff("ann")
        self.admin = staff("boss", "manage_mail_limits")
        settings_row = MailSettings.load()
        settings_row.default_daily_limit = 3
        settings_row.save()
        self.client.force_login(self.ann)

    def compose(self, to):
        return self.client.post("/api/messaging/mail/compose/", {
            "to": to, "subject": "Hi", "body": "Hello",
        }, content_type="application/json")

    def test_limit_counts_recipients_not_messages(self):
        self.assertEqual(self.compose("a@example.com, b@example.com").status_code, 201)
        resp = self.compose("c@example.com, d@example.com")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("1 of your 3 left today", resp.json()["detail"])
        self.assertEqual(self.compose("c@example.com").status_code, 201)
        self.assertEqual(self.compose("e@example.com").status_code, 429)
        self.assertEqual(MailMessage.objects.filter(direction="out").count(), 2)

    def test_hitting_the_limit_tells_the_admins_once(self):
        self.compose("a@example.com, b@example.com, c@example.com")
        mail.outbox.clear()
        self.compose("d@example.com")
        self.compose("d@example.com")
        notices = [m for m in mail.outbox if "reached their daily mail limit" in m.subject]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].to, ["boss@personal.example"])

    def test_a_personal_override_and_suspension(self):
        StaffProfile.objects.create(user=self.ann, daily_mail_limit=0)
        resp = self.compose("a@example.com")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("suspended", resp.json()["detail"])

    def test_yesterdays_mail_does_not_count(self):
        self.compose("a@example.com, b@example.com, c@example.com")
        MailMessage.objects.update(created_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.compose("d@example.com").status_code, 201)

    def test_monthly_cap_covers_the_whole_company(self):
        settings_row = MailSettings.load()
        settings_row.monthly_cap = 2
        settings_row.default_daily_limit = 100
        settings_row.save()
        self.assertEqual(self.compose("a@example.com, b@example.com").status_code, 201)
        self.client.force_login(self.admin)
        resp = self.compose("c@example.com")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("this month", resp.json()["detail"])

    def test_mailboxes_reports_the_quota(self):
        self.compose("a@example.com")
        quota = self.client.get("/api/messaging/mail/mailboxes/").json()["quota"]
        self.assertEqual((quota["used"], quota["limit"], quota["remaining"]), (1, 3, 2))

    def test_only_limit_managers_can_change_limits(self):
        self.assertEqual(self.client.get("/api/messaging/mail/limits/").status_code, 403)
        resp = self.client.patch(f"/api/messaging/mail/limits/people/{self.ann.pk}/",
                                 {"limit": 500}, content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_manager_sets_limits_and_it_is_audited(self):
        self.client.force_login(self.admin)
        resp = self.client.patch(f"/api/messaging/mail/limits/people/{self.ann.pk}/",
                                 {"limit": 50}, content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        row = next(p for p in resp.json()["people"] if p["id"] == self.ann.pk)
        self.assertEqual((row["limit"], row["effective"]), (50, 50))
        self.assertTrue(AuditEntry.objects.filter(
            action="mail_limit_changed", target_user=self.ann).exists())

        # null returns them to the default.
        resp = self.client.patch(f"/api/messaging/mail/limits/people/{self.ann.pk}/",
                                 {"limit": None}, content_type="application/json")
        row = next(p for p in resp.json()["people"] if p["id"] == self.ann.pk)
        self.assertEqual((row["limit"], row["effective"]), (None, 3))

        resp = self.client.patch("/api/messaging/mail/limits/",
                                 {"default_daily_limit": 40, "monthly_cap": 2500},
                                 content_type="application/json")
        self.assertEqual((resp.json()["default_daily_limit"], resp.json()["monthly_cap"]), (40, 2500))
        bad = self.client.patch("/api/messaging/mail/limits/", {"monthly_cap": -1},
                                content_type="application/json")
        self.assertEqual(bad.status_code, 400)
