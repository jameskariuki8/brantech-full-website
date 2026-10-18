"""Staff mailboxes: routing inbound mail to them and sending from them.

A mailbox is the local part of <mailbox>@MAILBOX_DOMAIN. Staff handles are
personal mailboxes, and each person sees only their own. SHARED_MAILBOXES,
and OTHER (anything addressed to a name nobody owns, so mail to a typo or a
departed colleague is never silently dropped), belong to the superuser, who
also reads every mailbox for oversight. That is a fixed rule, not a
capability: it cannot be handed out by giving someone a role.
"""

import email.utils
import html
import mimetypes
import os
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from staff.handles import SHARED_MAILBOXES, mailbox_address

from .models import BlockedSender, MailAttachment, MailMessage, MailThread, attachment_path

OTHER = "other"
SHARED = (*SHARED_MAILBOXES, OTHER)
ORG_NAME = "Teklora"


# Mailgun takes up to 25 MB a message; this leaves room for the encoding.
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
# Providers refuse these outright, so refuse them before the send rather
# than report a delivery failure afterwards.
BLOCKED_EXTENSIONS = {
    ".ade", ".adp", ".apk", ".app", ".bat", ".cab", ".chm", ".cmd", ".com", ".cpl",
    ".dll", ".dmg", ".exe", ".hta", ".ins", ".isp", ".jar", ".js", ".jse", ".lib",
    ".lnk", ".mde", ".msc", ".msi", ".msp", ".mst", ".pif", ".ps1", ".scr", ".sct",
    ".shb", ".sys", ".vb", ".vbe", ".vbs", ".vxd", ".wsc", ".wsf", ".wsh",
}


def attachment_problem(files):
    """Why these outgoing files cannot be sent, or None when they can."""
    if len(files) > MAX_ATTACHMENTS:
        return f"Attach at most {MAX_ATTACHMENTS} files."
    for f in files:
        ext = os.path.splitext(f.name or "")[1].lower()
        if ext in BLOCKED_EXTENSIONS:
            return f"{f.name}: {ext} files are blocked by mail providers. Zip it or share a link."
    if sum(f.size or 0 for f in files) > MAX_ATTACHMENT_BYTES:
        return "Attachments can total at most 20 MB. Share larger files as a link."
    return None


def _content_type(upload):
    given = (getattr(upload, "content_type", "") or "").strip()
    if given:
        return given[:150]
    return mimetypes.guess_type(upload.name or "")[0] or "application/octet-stream"


def store_inbound_files(uploads):
    """Save received files once. Returns descriptions deliver_inbound turns
    into MailAttachment rows for every mailbox copy of the message."""
    storage = MailAttachment._meta.get_field("file").storage
    stored = []
    for upload in uploads:
        name = os.path.basename(upload.name or "") or "attachment"
        path = storage.save(attachment_path(None, name), upload)
        stored.append({
            "file": path,
            "name": name[:255],
            "content_type": _content_type(upload),
            "size": upload.size or 0,
        })
    return stored


def discard_stored_files(stored):
    storage = MailAttachment._meta.get_field("file").storage
    for info in stored:
        storage.delete(info["file"])


def _clean_id(value):
    return (value or "").strip().strip("<>").strip()


def _id_list(value):
    return [_clean_id(v) for v in re.findall(r"<([^>]+)>", value or "")]


def snippet_of(text, length=180):
    return re.sub(r"\s+", " ", text or "").strip()[:length]


def local_parts(raw_recipients):
    """The mailboxes on our domain among a To/recipient header, in order."""
    suffix = "@" + settings.MAILBOX_DOMAIN.lower()
    found = []
    for _name, address in email.utils.getaddresses([raw_recipients or ""]):
        address = address.strip().lower()
        if address.endswith(suffix):
            local = address[: -len(suffix)].split("+", 1)[0]
            if local and local not in found:
                found.append(local)
    return found


def resolve_mailbox(local):
    """(mailbox, owner) for a local part."""
    owner = User.objects.filter(
        username__iexact=local, is_staff=True, is_active=True
    ).first()
    if owner is not None:
        return owner.username, owner
    if local in SHARED_MAILBOXES:
        return local, None
    return OTHER, None


def _find_thread(mailbox, owner, reference_ids):
    if not reference_ids:
        return None
    message = (
        MailMessage.objects.filter(
            thread__mailbox=mailbox, thread__owner=owner, message_id__in=reference_ids
        )
        .select_related("thread")
        .order_by("-created_at")
        .first()
    )
    return message.thread if message else None


def deliver_inbound(
    *,
    mailbox,
    delivered_to="",
    owner,
    from_name,
    from_email,
    to,
    cc,
    subject,
    body_text,
    body_html="",
    message_id="",
    in_reply_to="",
    references="",
    attachments=None,
    stored_files=None,
    snippet_text="",
):
    """File one received message into one mailbox. Returns the MailMessage,
    or None when this mailbox already holds it (Mailgun retries a webhook
    that timed out, and a message to two aliases of one person arrives twice).
    """
    message_id = _clean_id(message_id)
    in_reply_to = _clean_id(in_reply_to)
    with transaction.atomic():
        if message_id and MailMessage.objects.filter(
            thread__mailbox=mailbox, thread__owner=owner, message_id=message_id
        ).exists():
            return None

        reference_ids = _id_list(references) + ([in_reply_to] if in_reply_to else [])
        thread = _find_thread(mailbox, owner, reference_ids)
        now = timezone.now()
        if thread is None:
            thread = MailThread(mailbox=mailbox, owner=owner, subject=subject[:500])
        thread.counterpart_name = from_name[:200]
        thread.counterpart_email = from_email
        thread.snippet = snippet_of(snippet_text or body_text)
        thread.unread = True
        thread.archived = False
        # A new message is new mail, so a deleted conversation comes back.
        thread.deleted_at = None
        thread.deleted_by = None
        if BlockedSender.is_blocked(from_email):
            thread.spam = True
        thread.last_message_at = now
        thread.save()

        message = MailMessage.objects.create(
            thread=thread,
            direction="in",
            from_name=from_name[:200],
            from_email=from_email,
            to=to,
            cc=cc,
            delivered_to=delivered_to,
            subject=subject[:500],
            body_text=body_text,
            body_html=body_html,
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references or "",
            attachments=attachments or [],
            status="received",
        )
        MailAttachment.objects.bulk_create(
            MailAttachment(message=message, **info) for info in stored_files or []
        )
        return message


def claim_unmatched(user):
    """Move mail that reached <handle>@ before anyone owned it into the
    mailbox of the person who just claimed that handle."""
    address = mailbox_address(user.username)
    thread_ids = MailMessage.objects.filter(
        thread__owner__isnull=True, thread__mailbox=OTHER, delivered_to__iexact=address
    ).values_list("thread_id", flat=True)
    return MailThread.objects.filter(pk__in=list(thread_ids)).update(
        mailbox=user.username, owner=user
    )


# --- who may do what ------------------------------------------------------


def own_mailbox(user):
    """The user's personal mailbox name, or None before they pick a handle."""
    if not user.is_staff or "@" in user.username:
        return None
    return user.username


def is_admin(user):
    """The superuser: shared mailboxes, every inquiry, and oversight of
    every mailbox are theirs alone."""
    return bool(user and user.is_active and user.is_superuser)


def can_read(user, thread):
    if thread.owner_id is not None and thread.owner_id == user.pk:
        return True
    return is_admin(user)


def can_act(user, thread):
    """Reply, archive, mark unread. Oversight is read-only: an administrator
    reading a colleague's mailbox cannot answer as them or move their mail."""
    if thread.deleted_at is not None:
        return False
    if thread.owner_id is not None:
        return thread.owner_id == user.pk
    return is_admin(user)


def set_spam(user, thread, spam):
    """Flag or clear a thread as spam, blocking or unblocking its sender."""
    thread.spam = spam
    if spam:
        thread.unread = False
    thread.save(update_fields=["spam", "unread"])
    sender = thread.counterpart_email.strip().lower()
    if not sender or sender.endswith("@" + settings.MAILBOX_DOMAIN.lower()):
        # Never block our own addresses; a colleague is not spam.
        return
    if spam:
        BlockedSender.objects.get_or_create(email=sender, defaults={"blocked_by": user})
    else:
        BlockedSender.objects.filter(email__iexact=sender).delete()


def marks_read_on_open(user, thread):
    if thread.owner_id is not None:
        return thread.owner_id == user.pk
    return is_admin(user)


# --- sending ---------------------------------------------------------------


def _from_header(user, mailbox, owner):
    address = mailbox_address(mailbox)
    if owner is not None:
        name = user.get_full_name() or user.username
    else:
        name = ORG_NAME
    return email.utils.formataddr((name, address))


def _html_body(text):
    paragraphs = html.escape(text).split("\n\n")
    return "".join(
        f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs if p.strip()
    )


class SendError(Exception):
    pass


def send(user, *, mailbox, owner, to, cc, subject, body, thread=None, attachments=()):
    """Send from a mailbox and file the copy in it. Raises SendError when the
    provider refuses, in which case nothing is recorded.

    attachments are uploaded files, already checked by attachment_problem.
    They are stored only once the provider has accepted the message."""
    message_id = email.utils.make_msgid(domain=settings.MAILBOX_DOMAIN)
    headers = {"Message-ID": message_id}
    in_reply_to = ""
    references = ""
    if thread is not None:
        previous = thread.messages.exclude(message_id="").order_by("-created_at").first()
        if previous is not None:
            in_reply_to = previous.message_id
            chain = _id_list(previous.references) + [previous.message_id]
            references = " ".join(f"<{i}>" for i in chain[-20:])
            headers["In-Reply-To"] = f"<{in_reply_to}>"
            headers["References"] = references

    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=_from_header(user, mailbox, owner),
        to=to,
        cc=cc,
        headers=headers,
    )
    message.attach_alternative(_html_body(body), "text/html")
    files = []
    for upload in attachments:
        name = os.path.basename(upload.name or "") or "attachment"
        upload.seek(0)
        files.append((name[:255], upload.read(), _content_type(upload)))
    for name, content, content_type in files:
        message.attach(name, content, content_type)
    try:
        message.send(fail_silently=False)
    except Exception as exc:  # the backend raises RuntimeError or a network error
        raise SendError(str(exc)) from exc

    now = timezone.now()
    with transaction.atomic():
        if thread is None:
            first = email.utils.getaddresses([to[0]])[0] if to else ("", "")
            thread = MailThread(
                mailbox=mailbox,
                owner=owner,
                subject=subject[:500],
                counterpart_name=first[0][:200],
                counterpart_email=first[1],
            )
        thread.snippet = snippet_of(body)
        thread.unread = False
        thread.archived = False
        thread.last_message_at = now
        thread.save()
        sent = MailMessage.objects.create(
            thread=thread,
            direction="out",
            from_name=(user.get_full_name() or user.username)[:200],
            from_email=mailbox_address(mailbox),
            to=to,
            cc=cc,
            subject=subject[:500],
            body_text=body,
            body_html="",
            message_id=_clean_id(message_id),
            in_reply_to=in_reply_to,
            references=references,
            sent_by=user,
            status="sent",
        )
        for name, content, content_type in files:
            row = MailAttachment(
                message=sent, name=name, content_type=content_type, size=len(content)
            )
            row.file.save(name, ContentFile(content), save=False)
            row.save()
        return sent
