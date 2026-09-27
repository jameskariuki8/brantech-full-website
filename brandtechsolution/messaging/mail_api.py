"""The panel's mail client: every staff member's own mailbox, the shared
mailboxes for view_inbox holders, and every mailbox for view_all_mail."""

import email.utils

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from staff.handles import mailbox_address

from . import mailbox as mb
from .models import MailThread


class ThreadPagination(PageNumberPagination):
    page_size = 30


def _thread_json(thread):
    return {
        "id": thread.id,
        "mailbox": thread.mailbox,
        "address": mailbox_address(thread.mailbox),
        "owner": thread.owner.username if thread.owner_id else None,
        "subject": thread.subject,
        "counterpart_name": thread.counterpart_name,
        "counterpart_email": thread.counterpart_email,
        "snippet": thread.snippet,
        "unread": thread.unread,
        "archived": thread.archived,
        "spam": thread.spam,
        "deleted": thread.deleted_at is not None,
        "last_message_at": thread.last_message_at,
        "message_count": getattr(thread, "message_count", None),
        "has_sent": getattr(thread, "has_sent", None),
    }


def _message_json(message):
    return {
        "id": message.id,
        "direction": message.direction,
        "from_name": message.from_name,
        "from_email": message.from_email,
        "to": message.to,
        "cc": message.cc,
        "subject": message.subject,
        "body_text": message.body_text,
        "body_html": message.body_html,
        "attachments": message.attachments,
        "sent_by": message.sent_by.username if message.sent_by_id else None,
        "status": message.status,
        "created_at": message.created_at,
    }


def _visible(user):
    """Threads the user may read, before any mailbox filter."""
    if user.has_perm("staff.view_all_mail"):
        return MailThread.objects.all()
    q = Q(owner=user)
    if user.has_perm("staff.view_inbox"):
        q |= Q(owner__isnull=True)
    return MailThread.objects.filter(q)


@api_view(["GET"])
@permission_classes([IsAdminUser])
def mailboxes(request):
    user = request.user
    own = mb.own_mailbox(user)
    unread = dict(
        _visible(user).filter(unread=True, archived=False, spam=False, deleted_at__isnull=True)
        .values_list("mailbox").annotate(n=Count("id")).values_list("mailbox", "n")
    )
    data = {
        "me": (
            {"mailbox": own, "address": mailbox_address(own), "unread": unread.get(own, 0)}
            if own else None
        ),
        "shared": [],
        "all_mail": user.has_perm("staff.view_all_mail"),
        "people": [],
    }
    if user.has_perm("staff.view_inbox"):
        data["shared"] = [
            {
                "mailbox": name,
                "address": mailbox_address(name) if name != mb.OTHER else "Unmatched addresses",
                "unread": unread.get(name, 0),
                "can_send": name != mb.OTHER and user.has_perm("staff.handle_inquiries"),
            }
            for name in mb.SHARED
        ]
    if data["all_mail"]:
        data["people"] = [
            {"id": u.id, "mailbox": u.username, "name": u.get_full_name() or u.username}
            for u in User.objects.filter(is_staff=True, is_active=True)
            .exclude(username__contains="@").order_by("username")
        ]
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAdminUser])
def threads(request):
    user = request.user
    box = request.query_params.get("box") or "me"
    qs = _visible(user)

    if box in ("me", "sent"):
        qs = qs.filter(owner=user)
        if box == "sent":
            qs = qs.filter(messages__direction="out").distinct()
    elif box in mb.SHARED:
        if not user.has_perm("staff.view_inbox"):
            raise PermissionDenied("You need the view_inbox capability.")
        qs = qs.filter(owner__isnull=True, mailbox=box)
    elif box == "all":
        if not user.has_perm("staff.view_all_mail"):
            raise PermissionDenied("You need the view_all_mail capability.")
        person = request.query_params.get("person")
        if person:
            qs = qs.filter(owner_id=person)
        direction = request.query_params.get("direction")
        if direction in ("in", "out"):
            qs = qs.filter(messages__direction=direction).distinct()
    else:
        raise ValidationError({"box": "Unknown mailbox."})

    if box != "all":
        # Deleted mail is gone from mailboxes; only oversight still lists it.
        qs = qs.filter(deleted_at__isnull=True)
    if request.query_params.get("spam") == "1":
        qs = qs.filter(spam=True)
    else:
        qs = qs.filter(spam=False)
        if box != "sent":
            qs = qs.filter(archived=request.query_params.get("archived") == "1")
    if request.query_params.get("unread") == "1":
        qs = qs.filter(unread=True)

    term = (request.query_params.get("q") or "").strip()
    if term:
        qs = qs.filter(
            Q(subject__icontains=term)
            | Q(counterpart_name__icontains=term)
            | Q(counterpart_email__icontains=term)
            | Q(messages__body_text__icontains=term)
        ).distinct()

    qs = qs.select_related("owner").annotate(
        message_count=Count("messages", distinct=True),
        has_sent=Count("messages", filter=Q(messages__direction="out"), distinct=True),
    ).order_by("-last_message_at")
    paginator = ThreadPagination()
    page = paginator.paginate_queryset(qs, request)
    return paginator.get_paginated_response([_thread_json(t) for t in page])


def _get_thread(request, pk):
    thread = get_object_or_404(MailThread.objects.select_related("owner"), pk=pk)
    if not mb.can_read(request.user, thread):
        # 404 rather than 403: whether a colleague has a thread is itself private.
        raise Http404
    if thread.deleted_at and not request.user.has_perm("staff.view_all_mail"):
        raise Http404
    return thread


@api_view(["GET"])
@permission_classes([IsAdminUser])
def thread_detail(request, pk):
    thread = _get_thread(request, pk)
    if thread.unread and mb.marks_read_on_open(request.user, thread):
        thread.unread = False
        thread.save(update_fields=["unread"])
    messages = thread.messages.select_related("sent_by").order_by("created_at")
    data = _thread_json(thread)
    data["can_act"] = mb.can_act(request.user, thread)
    data["messages"] = [_message_json(m) for m in messages]
    return Response(data)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def thread_state(request, pk):
    thread = _get_thread(request, pk)
    if not mb.can_act(request.user, thread):
        raise PermissionDenied("You can read this conversation but not change it.")
    fields = []
    for field in ("unread", "archived"):
        if field in request.data:
            setattr(thread, field, bool(request.data[field]))
            fields.append(field)
    if fields:
        thread.save(update_fields=fields)
    if "spam" in request.data:
        mb.set_spam(request.user, thread, bool(request.data["spam"]))
    return Response(_thread_json(thread))


@api_view(["POST"])
@permission_classes([IsAdminUser])
def delete_thread(request, pk):
    thread = _get_thread(request, pk)
    if not mb.can_act(request.user, thread):
        raise PermissionDenied("Only the mailbox's owner can delete from it.")
    thread.deleted_at = timezone.now()
    thread.deleted_by = request.user
    thread.save(update_fields=["deleted_at", "deleted_by"])
    return Response(status=204)


def _recipients(raw, field, required=False):
    """A list of addresses from a comma-separated string or a list."""
    if isinstance(raw, str):
        raw = [raw]
    parsed = email.utils.getaddresses([str(r) for r in (raw or [])])
    addresses = []
    for name, address in parsed:
        if not address:
            continue
        try:
            validate_email(address)
        except DjangoValidationError:
            raise ValidationError({field: f"'{address}' is not a valid email address."})
        addresses.append(email.utils.formataddr((name, address)) if name else address)
    if required and not addresses:
        raise ValidationError({field: "Add at least one recipient."})
    if len(addresses) > 20:
        raise ValidationError({field: "At most 20 recipients per message."})
    return addresses


def _body(request):
    body = (request.data.get("body") or "").strip()
    if not body:
        raise ValidationError({"body": "Write a message first."})
    return body


def _send(request, **kwargs):
    try:
        message = mb.send(request.user, **kwargs)
    except mb.SendError as exc:
        return Response({"detail": f"The message was not sent: {exc}"}, status=502)
    data = _thread_json(message.thread)
    data["message"] = _message_json(message)
    return Response(data, status=201)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def reply(request, pk):
    thread = _get_thread(request, pk)
    if not mb.can_act(request.user, thread):
        raise PermissionDenied("Only the mailbox's owner can reply from it.")
    body = _body(request)
    last_in = thread.messages.filter(direction="in").order_by("-created_at").first()
    default_to = [last_in.from_email] if last_in else [thread.counterpart_email]
    to = _recipients(request.data.get("to") or default_to, "to", required=True)
    cc = _recipients(request.data.get("cc"), "cc")
    subject = thread.subject or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()
    return _send(
        request, mailbox=thread.mailbox, owner=thread.owner, to=to, cc=cc,
        subject=subject, body=body, thread=thread,
    )


@api_view(["POST"])
@permission_classes([IsAdminUser])
def compose(request):
    user = request.user
    source = request.data.get("from") or "me"
    if source == "me":
        mailbox = mb.own_mailbox(user)
        if mailbox is None:
            raise PermissionDenied("Choose your work address before sending mail.")
        owner = user
    elif source in mb.SHARED_MAILBOXES:
        if not user.has_perm("staff.handle_inquiries"):
            raise PermissionDenied("You need handle_inquiries to send from a shared address.")
        mailbox, owner = source, None
    else:
        raise ValidationError({"from": "Unknown mailbox."})

    subject = (request.data.get("subject") or "").strip()
    if not subject:
        raise ValidationError({"subject": "Add a subject."})
    return _send(
        request,
        mailbox=mailbox,
        owner=owner,
        to=_recipients(request.data.get("to"), "to", required=True),
        cc=_recipients(request.data.get("cc"), "cc"),
        subject=subject[:500],
        body=_body(request),
    )


# The sidebar's unread badge.
@api_view(["GET"])
@permission_classes([IsAdminUser])
def unread_count(request):
    user = request.user
    q = Q(owner=user)
    if user.has_perm("staff.view_inbox"):
        q |= Q(owner__isnull=True)
    count = MailThread.objects.filter(
        q, unread=True, archived=False, spam=False, deleted_at__isnull=True
    ).count()
    return Response({"unread": count})

