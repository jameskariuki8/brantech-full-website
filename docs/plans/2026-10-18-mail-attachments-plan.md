# Mail attachments

Date: 2026-10-18
Branch: `feat/mail-attachments`

## Problem

The panel mail client has no attachments anywhere:

- **Sending**: compose and reply accept only text. There is no way to attach a file.
- **Receiving**: the Mailgun inbound webhook records each attachment's name, size and type in `MailMessage.attachments` (JSON), then throws the file away. The reader shows those names as grey chips with "Attachments are not stored yet".

The Mailgun backend (`brandtechsolution/mailgun.py`) already forwards Django `EmailMessage.attachments`, so the provider side needs no change.

## Constraints

- `/media/` is served to anyone, without authentication (`brandtechsolution/urls.py`). Mail is private, so attachments must never be stored under `MEDIA_ROOT`.
- Access follows the thread: whoever may read a thread (`mailbox.can_read`) may download its files, and nobody else. A refused download returns 404, the same as the thread itself.
- Inbound files are untrusted. They are always served as downloads (`Content-Disposition: attachment`, `nosniff`, a sandbox CSP), never rendered inline on our origin.
- Mailgun accepts messages up to 25 MB. Outbound limits: 10 files, 20 MB in total, and no executable types, since providers reject those anyway.

## Design

1. **Storage**: `MAIL_ATTACHMENTS_ROOT` comes from config (`mail_attachments_root`, default `brandtechsolution/private/mail_attachments`). It uses a `FileSystemStorage` with no `base_url`. Docker mounts `./data/private` into `web`.
2. **Model**: `MailAttachment(message FK related_name="files", file, name, content_type, size, created_at)`. One inbound email filed into several mailboxes stores each file once, and every copy's row points at the same stored file.
3. **Inbound**: the webhook saves `request.FILES` once and passes the stored files to `deliver_inbound`, which creates the rows. The `attachments` JSON stays as it is for older messages, which keep showing their names as "not stored".
4. **Outbound**: `compose` and `reply` also accept `multipart/form-data` with repeated `attachments` file fields. JSON still works. `mailbox.send` attaches the files to the outgoing message, and stores them only after the provider accepts it. A failed send records nothing, which is the existing rule.
5. **Download**: `GET /api/messaging/mail/attachments/<id>/` checks `can_read` on the attachment's thread.
6. **UI**: an "Attach" button and a file list in both the compose modal and the reply box, with size and count checked before upload. In the reader, stored attachments become download links.

## Out of scope

Attachments on campaigns. A bulk send with a file multiplies its size by every recipient and hurts deliverability. Campaigns should link to hosted files instead.

## Tests

`messaging/tests/test_mail_attachments.py` covers:

- an inbound file is stored and can be downloaded
- other people get 404
- an inbound email to two mailboxes stores the file once
- compose and reply with files deliver them and record them
- limits and blocked types are refused before sending
- a provider failure leaves no files recorded
