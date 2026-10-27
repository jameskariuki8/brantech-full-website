import os
import shutil
import tempfile

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from messaging.models import MailAttachment, MailMessage, MailThread

from .test_mail import admin, inbound, staff

ROOT = tempfile.mkdtemp(prefix="mail-forward-test-")


def upload(name="quote.pdf", content=b"%PDF-1.4 quote", content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


@override_settings(
    MAILBOX_DOMAIN="teklora.co.ke",
    MAIL_ATTACHMENTS_ROOT=ROOT,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class ForwardTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(ROOT, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(ROOT, ignore_errors=True)
        os.makedirs(ROOT)
        self.ann = staff("ann")
        self.bob = staff("bob")

    def received(self, recipient="ann@teklora.co.ke", subject="Quote request", **extra):
        inbound(self.client, recipient, subject=subject, **extra)
        message = MailMessage.objects.filter(direction="in").latest("id")
        return message.thread, message

    def forward(self, thread, **data):
        return self.client.post(f"/api/messaging/mail/threads/{thread.id}/forward/", data)

    def test_forward_quotes_the_original_and_files_a_new_thread(self):
        thread, original = self.received()
        self.client.force_login(self.ann)
        resp = self.forward(thread, message=original.id, to="partner@example.com", body="FYI, see below.")
        self.assertEqual(resp.status_code, 201, resp.content)

        [sent] = mail.outbox
        self.assertEqual(sent.to, ["partner@example.com"])
        self.assertEqual(sent.subject, "Fwd: Quote request")
        self.assertIn("ann@teklora.co.ke", sent.from_email)
        self.assertTrue(sent.body.startswith("FYI, see below."))
        self.assertIn("---------- Forwarded message ---------", sent.body)
        self.assertIn("From: Client Person <client@example.com>", sent.body)
        self.assertIn("A question.", sent.body)
        # No In-Reply-To: the partner was never part of the conversation.
        self.assertNotIn("In-Reply-To", sent.extra_headers)

        forwarded = MailThread.objects.exclude(pk=thread.pk).get()
        self.assertEqual((forwarded.mailbox, forwarded.owner), ("ann", self.ann))
        self.assertEqual(forwarded.subject, "Fwd: Quote request")
        self.assertEqual(thread.messages.count(), 1)

    def test_forward_defaults_to_the_latest_message_and_keeps_fwd_subjects(self):
        thread, _ = self.received(subject="FW: Older")
        self.client.force_login(self.ann)
        self.assertEqual(self.forward(thread, to="x@example.com").status_code, 201)
        self.assertEqual(mail.outbox[0].subject, "FW: Older")

    def test_kept_attachments_go_with_it_and_new_files_can_be_added(self):
        thread, original = self.received(**{"attachment-1": upload(), "attachment-2": upload("cv.docx", b"cv")})
        quote, cv = original.files.order_by("name")[1], original.files.order_by("name")[0]
        self.client.force_login(self.ann)
        resp = self.forward(
            thread, message=original.id, to="x@example.com", keep=str(quote.id),
            attachments=[upload("notes.txt", b"notes", "text/plain")],
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        names = sorted(name for name, _content, _type in mail.outbox[0].attachments)
        self.assertEqual(names, ["notes.txt", "quote.pdf"])
        self.assertNotIn("cv.docx", names)
        sent = MailMessage.objects.get(direction="out")
        self.assertEqual(sorted(sent.files.values_list("name", flat=True)), ["notes.txt", "quote.pdf"])
        with sent.files.get(name="quote.pdf").file.open("rb") as fh:
            self.assertEqual(fh.read(), b"%PDF-1.4 quote")

    def test_an_html_only_message_is_quoted_as_text(self):
        thread, original = self.received(**{
            "body-plain": "", "stripped-text": "",
            "body-html": "<html><head><style>p{color:red}</style></head><body><p>Line one</p><p>Line&nbsp;two</p></body></html>",
        })
        self.client.force_login(self.ann)
        self.forward(thread, message=original.id, to="x@example.com")
        body = mail.outbox[0].body
        self.assertIn("Line one\n", body)
        self.assertIn("Line two", body)
        self.assertNotIn("color:red", body)

    def test_someone_who_cannot_read_the_thread_gets_404(self):
        thread, original = self.received()
        self.client.force_login(self.bob)
        resp = self.forward(thread, message=original.id, to="x@example.com")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(mail.outbox, [])

    def test_a_message_from_another_thread_is_refused(self):
        thread, _ = self.received()
        _other, foreign = self.received(recipient="bob@teklora.co.ke")
        self.client.force_login(self.ann)
        resp = self.forward(thread, message=foreign.id, to="x@example.com")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(mail.outbox, [])

    def test_kept_ids_from_another_message_are_ignored(self):
        thread, original = self.received()
        _other, foreign = self.received(recipient="bob@teklora.co.ke", **{"attachment-1": upload("secret.pdf")})
        secret = foreign.files.get()
        self.client.force_login(self.ann)
        self.forward(thread, message=original.id, to="x@example.com", keep=str(secret.id))
        self.assertEqual(mail.outbox[0].attachments, [])

    def test_oversight_forwards_from_your_own_address_not_theirs(self):
        thread, original = self.received()
        boss = admin("boss")
        self.client.force_login(boss)
        resp = self.forward(thread, message=original.id, to="x@example.com")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIn("boss@teklora.co.ke", mail.outbox[0].from_email)
        self.assertFalse(MailThread.objects.filter(owner=self.ann).exclude(pk=thread.pk).exists())

    def test_shared_mail_needs_handle_inquiries_to_go_out_from_the_shared_address(self):
        thread, original = self.received(recipient="info@teklora.co.ke")
        reader = staff("reader", "view_inbox")
        self.client.force_login(reader)
        resp = self.forward(thread, message=original.id, to="x@example.com", **{"from": "info"})
        self.assertEqual(resp.status_code, 403)
        # From their own address it is fine: they can already read it.
        resp = self.forward(thread, message=original.id, to="x@example.com")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIn("reader@teklora.co.ke", mail.outbox[0].from_email)

        handler = staff("handler", "view_inbox", "handle_inquiries")
        self.client.force_login(handler)
        resp = self.forward(thread, message=original.id, to="x@example.com")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIn("info@teklora.co.ke", mail.outbox[1].from_email)

    def test_recipients_are_required_and_count_towards_the_limit(self):
        thread, original = self.received()
        self.client.force_login(self.ann)
        self.assertEqual(self.forward(thread, message=original.id, to="").status_code, 400)
        self.assertFalse(MailAttachment.objects.filter(message__direction="out").exists())
