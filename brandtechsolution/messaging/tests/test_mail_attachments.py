import os
import shutil
import tempfile
from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from messaging.models import MailAttachment, MailMessage, MailThread

from .test_mail import admin, inbound, staff

ROOT = tempfile.mkdtemp(prefix="mail-attachments-test-")


def upload(name="quote.pdf", content=b"%PDF-1.4 quote", content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def stored_files():
    return sorted(
        os.path.relpath(os.path.join(d, f), ROOT)
        for d, _, files in os.walk(ROOT) for f in files
    )


@override_settings(
    MAILBOX_DOMAIN="teklora.co.ke",
    MAIL_ATTACHMENTS_ROOT=ROOT,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class MailAttachmentTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(ROOT, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(ROOT, ignore_errors=True)
        os.makedirs(ROOT)
        self.ann = staff("ann")
        self.bob = staff("bob")
        self.boss = admin("boss")

    def receive(self, recipient="ann@teklora.co.ke", **files):
        return inbound(self.client, recipient, **files)

    def detail(self, thread):
        return self.client.get(f"/api/messaging/mail/threads/{thread.id}/").json()

    # --- receiving ---------------------------------------------------------

    def test_a_received_file_is_kept_and_downloadable_by_the_owner(self):
        self.receive(**{"attachment-count": "1", "attachment-1": upload()})
        thread = MailThread.objects.get()
        self.client.force_login(self.ann)
        [att] = self.detail(thread)["messages"][0]["attachments"]
        self.assertEqual((att["name"], att["size"]), ("quote.pdf", 14))
        resp = self.client.get(att["url"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), b"%PDF-1.4 quote")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn("quote.pdf", resp["Content-Disposition"])
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_attachments_are_not_in_public_media(self):
        self.receive(**{"attachment-1": upload()})
        item = MailAttachment.objects.get()
        self.assertTrue(item.file.path.startswith(os.path.abspath(ROOT)))
        self.assertNotIn("quote", item.file.name)
        with self.assertRaises(ValueError):
            item.file.url

    def test_people_who_cannot_read_the_thread_get_404(self):
        self.receive(**{"attachment-1": upload()})
        item = MailAttachment.objects.get()
        url = f"/api/messaging/mail/attachments/{item.id}/"
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.logout()
        self.assertIn(self.client.get(url).status_code, (401, 403))

    def test_mail_to_two_mailboxes_stores_the_file_once(self):
        self.receive("ann@teklora.co.ke, bob@teklora.co.ke", **{"attachment-1": upload()})
        self.assertEqual(MailAttachment.objects.count(), 2)
        self.assertEqual(len(stored_files()), 1)
        self.assertEqual(len({a.file.name for a in MailAttachment.objects.all()}), 1)

    def test_a_retried_webhook_leaves_no_stray_file(self):
        headers = {"Message-Id": "<same@example.com>"}
        self.receive(**headers, **{"attachment-1": upload()})
        self.receive(**headers, **{"attachment-1": upload()})
        self.assertEqual(MailMessage.objects.count(), 1)
        self.assertEqual(len(stored_files()), 1)

    def test_older_mail_lists_names_without_a_link(self):
        self.receive()
        message = MailMessage.objects.get()
        message.attachments = [{"name": "old.pdf", "size": 5, "content_type": "application/pdf"}]
        message.save()
        self.client.force_login(self.ann)
        [att] = self.detail(message.thread)["messages"][0]["attachments"]
        self.assertEqual(att["name"], "old.pdf")
        self.assertIsNone(att["url"])

    # --- sending -----------------------------------------------------------

    def test_compose_with_files_sends_and_records_them(self):
        self.client.force_login(self.ann)
        resp = self.client.post("/api/messaging/mail/compose/", {
            "from": "me", "to": "client@example.com", "subject": "Proposal",
            "body": "Attached.",
            "attachments": [upload(), upload("notes.txt", b"notes", "text/plain")],
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        sent = mail.outbox[0]
        self.assertEqual(
            [(n, c) for n, c, _ in sent.attachments],
            # Django hands text/* parts over decoded.
            [("quote.pdf", b"%PDF-1.4 quote"), ("notes.txt", "notes")],
        )
        names = [a["name"] for a in resp.json()["message"]["attachments"]]
        self.assertEqual(names, ["quote.pdf", "notes.txt"])
        self.assertEqual(len(stored_files()), 2)

    def test_reply_with_a_file(self):
        self.receive()
        mail.outbox.clear()
        thread = MailThread.objects.get()
        self.client.force_login(self.ann)
        resp = self.client.post(
            f"/api/messaging/mail/threads/{thread.id}/reply/",
            {"body": "Here it is.", "attachments": upload()},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(mail.outbox[0].attachments[0][0], "quote.pdf")
        self.assertEqual(thread.messages.get(direction="out").files.count(), 1)

    def test_json_sending_still_works(self):
        self.client.force_login(self.ann)
        resp = self.client.post("/api/messaging/mail/compose/", {
            "to": "client@example.com", "subject": "Hi", "body": "No files."},
            content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(mail.outbox[0].attachments, [])

    def test_blocked_types_too_many_and_too_large_are_refused_before_sending(self):
        self.client.force_login(self.ann)
        cases = [
            [upload("setup.EXE", b"MZ", "application/octet-stream")],
            [upload(f"f{i}.txt", b"x", "text/plain") for i in range(11)],
            [upload("big.bin", b"0" * (20 * 1024 * 1024 + 1), "application/octet-stream")],
        ]
        for files in cases:
            resp = self.client.post("/api/messaging/mail/compose/", {
                "to": "client@example.com", "subject": "x", "body": "y", "attachments": files})
            self.assertEqual(resp.status_code, 400, resp.content)
            self.assertIn("attachments", resp.json())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(stored_files(), [])

    def test_a_provider_failure_keeps_no_file(self):
        self.client.force_login(self.ann)
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=RuntimeError("down")):
            resp = self.client.post("/api/messaging/mail/compose/", {
                "to": "client@example.com", "subject": "x", "body": "y", "attachments": upload()})
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(MailAttachment.objects.exists())
        self.assertEqual(stored_files(), [])
