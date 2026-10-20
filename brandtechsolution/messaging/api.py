from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from staff.handles import mailbox_address
from staff.permissions import has_capability

from . import audience, quota
from . import campaigns as campaign_rules
from . import contacts as contact_rules
from .imports import UnsupportedFileType
from .models import (
    Campaign, CampaignExclusion, CampaignRecipient, Contact, EmailTemplate, Inquiry,
    MailSettings, Segment, Suppression,
)
from .outbox import send_campaign_email
from .serializers import (
    ADDABLE_CAMPAIGN_STATUSES,
    CampaignRecipientSerializer,
    CampaignSerializer,
    ContactSerializer,
    EmailTemplateSerializer,
    InquirySerializer,
    SegmentSerializer,
)
from .validation import validate_campaign_recipients


class InquiryViewSet(viewsets.ModelViewSet):
    serializer_class = InquirySerializer

    def get_queryset(self):
        qs = Inquiry.objects.all()
        status_param = self.request.query_params.get("status")
        if status_param and status_param != "all":
            qs = qs.filter(status=status_param)

        q_param = self.request.query_params.get("q") or self.request.query_params.get("search")
        if q_param:
            qs = qs.filter(
                Q(name__icontains=q_param)
                | Q(email__icontains=q_param)
                | Q(message__icontains=q_param)
            )
        return qs.order_by("-created_at")

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [has_capability("view_inbox")()]
        return [has_capability("handle_inquiries")()]

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        inquiry = self.get_object()
        reply_message = (request.data.get("message") or request.data.get("reply_message") or "").strip()
        if not reply_message:
            return Response({"ok": False, "error": "Reply message content cannot be empty."}, status=400)

        subject = f"Re: Technical Inquiry - Teklora Solutions"
        try:
            send_mail(
                subject=subject,
                message=reply_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[inquiry.email],
                fail_silently=False,
            )
        except Exception as e:
            return Response({"ok": False, "error": f"Failed to send email: {str(e)}"}, status=500)

        inquiry.status = "replied"
        sender_label = getattr(request.user, "username", "Staff")
        inquiry.message += f"\n\n--- STAFF REPLY ({sender_label}) ---\n{reply_message}"
        inquiry.save(update_fields=["status", "message"])

        return Response({"ok": True, "inquiry": self.get_serializer(inquiry).data})

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        inquiry = self.get_object()
        if inquiry.status == "new":
            inquiry.status = "read"
            inquiry.save(update_fields=["status"])
        return Response({"ok": True, "inquiry": self.get_serializer(inquiry).data})

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        inquiry = self.get_object()
        inquiry.status = "archived"
        inquiry.save(update_fields=["status"])
        return Response({"ok": True, "inquiry": self.get_serializer(inquiry).data})



class EmailTemplateViewSet(viewsets.ModelViewSet):
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer
    permission_classes = [has_capability("manage_templates")]


class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.select_related("template", "created_by")
    serializer_class = CampaignSerializer

    # Sending is the one irreversible, externally visible action, so it is
    # gated separately from ordinary campaign editing.
    ACTION_CAPABILITIES = {
        "build_recipients": "manage_recipients",
        "queue": "send_campaigns",
        "unqueue": "send_campaigns",
        "pause": "send_campaigns",
        "resume": "send_campaigns",
    }

    def get_permissions(self):
        capability = self.ACTION_CAPABILITIES.get(self.action, "manage_campaigns")
        return [has_capability(capability)()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        campaign = self.get_object()
        if campaign.status != "draft":
            return Response(
                {"detail": "Only a draft can be deleted. A queued or sent campaign is kept as a record."},
                status=400,
            )
        campaign.delete()
        return Response(status=204)

    @action(detail=False, methods=["get"])
    def overview(self, request):
        """What the campaigns page needs beyond the list: where it may send
        from and how much of the month is left."""
        mail_settings = MailSettings.load()
        used = quota.used_this_month()
        return Response({
            "senders": campaign_rules.sender_choices(request.user),
            "month": {
                "used": used,
                "cap": mail_settings.monthly_cap,
                "committed": campaign_rules.committed(),
                "headroom": campaign_rules.month_headroom(),
            },
            "can_send": request.user.has_perm("staff.send_campaigns"),
            "audience": _audience_choices(),
        })

    @action(detail=True, methods=["post"])
    def build_recipients(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != "draft":
            return Response(
                {"detail": "Recipients can only be built for a draft campaign."},
                status=400,
            )
        sources = request.data.get("sources", []) or []
        manual = request.data.get("manual_emails", []) or []
        try:
            segment_ids = [int(i) for i in request.data.get("segments", []) or []]
        except (TypeError, ValueError):
            return Response({"detail": "Segments must be ids."}, status=400)
        segments = list(Segment.objects.filter(pk__in=segment_ids))
        origins = [o for o in request.data.get("origins", []) or [] if o in contact_rules.SOURCE_LABELS]
        everyone = bool(request.data.get("everyone"))
        selection = {"everyone": everyone, "segments": [s.pk for s in segments], "origins": origins}
        count = audience.build_recipients(campaign, sources, manual, selection)

        # Say in words what went in, for the campaign's record.
        groups = dict(contact_rules.ORIGIN_GROUPS)
        labels = ["Everyone in contacts"] if everyone else (
            [s.name for s in segments] + [groups[o] for o in origins]
        )
        if manual:
            labels.append("Addresses added by hand")
        new = [label for label in labels if label not in campaign.audience]
        if new:
            campaign.audience = campaign.audience + new
            campaign.save(update_fields=["audience"])
        return Response({"count": count})

    @action(detail=True, methods=["post"])
    def queue(self, request, pk=None):
        send_at = None
        raw = request.data.get("send_at")
        if raw:
            send_at = parse_datetime(str(raw))
            if send_at is None:
                return Response({"detail": "The send time is not a valid date and time."}, status=400)
            if timezone.is_naive(send_at):
                send_at = timezone.make_aware(send_at)
            if send_at <= timezone.now():
                send_at = None

        with transaction.atomic():
            campaign = Campaign.objects.select_for_update().get(pk=self.get_object().pk)
            if campaign.status != "draft":
                return Response({"detail": "Only draft campaigns can be queued."}, status=400)
            if campaign.total == 0:
                return Response({"detail": "No recipients. Build recipients first."}, status=400)
            if campaign.template_id:
                campaign_rules.copy_template(campaign, campaign.template)
            if not campaign.body_html.strip():
                return Response({"detail": "The email has no content. Choose a template."}, status=400)

            # Checked at queue time so a campaign that cannot finish this
            # month is refused up front rather than stalling halfway.
            quota.lock()
            pending = campaign.recipients.filter(status="pending").count()
            headroom = campaign_rules.month_headroom(exclude=campaign)
            if pending > headroom:
                return Response({"detail": (
                    f"This campaign has {pending} recipients but only {headroom} are left "
                    "in this month's sending cap, after other queued campaigns. "
                    "Trim the audience or raise the cap under Mail, Sending limits."
                )}, status=400)

            campaign.status = "queued"
            campaign.send_at = send_at
            campaign.note = ""
            campaign.save(update_fields=[
                "status", "send_at", "note", "template", "subject", "body_source", "body_html",
            ])
        return Response(self.get_serializer(campaign).data)

    @action(detail=True, methods=["post"])
    def unqueue(self, request, pk=None):
        """Take a campaign that has not started back to draft, to change it."""
        updated = Campaign.objects.filter(
            pk=self.get_object().pk, status__in=("queued", "paused"), started_at__isnull=True,
        ).update(status="draft", send_at=None, note="")
        if not updated:
            return Response(
                {"detail": "Only a campaign that has not started sending can go back to draft."},
                status=400,
            )
        return Response(self.get_serializer(Campaign.objects.get(pk=pk)).data)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status not in ("queued", "sending"):
            return Response(
                {"detail": "Only queued or sending campaigns can be paused."},
                status=400,
            )
        campaign.status = "paused"
        campaign.save(update_fields=["status"])
        return Response({"status": campaign.status})

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != "paused":
            return Response(
                {"detail": "Only paused campaigns can be resumed."}, status=400
            )
        campaign.status = "queued"
        campaign.note = ""
        campaign.save(update_fields=["status", "note"])
        return Response({"status": campaign.status})

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        """Send the campaign as it stands to the person asking, marked as a
        test, so they see it in a real inbox before anyone else does."""
        campaign = self.get_object()
        user = request.user
        if campaign.template_id and campaign.status == "draft":
            campaign_rules.copy_template(campaign, campaign.template)
        if not campaign.body_html.strip():
            return Response({"detail": "The email has no content. Choose a template."}, status=400)
        to = mailbox_address(user.username) if "@" not in user.username else user.email
        if not to:
            return Response({"detail": "You have no address to send a test to."}, status=400)

        key = f"campaign-test:{user.pk}:{timezone.localdate()}"
        cache.add(key, 0, timeout=60 * 60 * 25)
        if cache.incr(key) > TEST_SENDS_PER_DAY:
            return Response(
                {"detail": f"That is {TEST_SENDS_PER_DAY} test sends today. Try again tomorrow."},
                status=429,
            )
        try:
            send_campaign_email(campaign, to, user.get_full_name(), test=True)
        except Exception as exc:  # the backend raises RuntimeError or a network error
            return Response({"detail": f"The test could not be sent: {exc}"}, status=502)
        return Response({"to": to})


TEST_SENDS_PER_DAY = 20


def _audience_choices():
    """What a campaign audience can be built from, and how many people each
    would actually reach once unsubscribed and bounced addresses are out."""
    reach = contact_rules.reachable()
    return {
        "everyone": reach.count(),
        "segments": [
            {"id": s.pk, "name": s.name, "count": reach.filter(segments=s).count()}
            for s in Segment.objects.all()
        ],
        "origins": [
            {"key": key, "label": label, "count": reach.filter(source=key).count()}
            for key, label in contact_rules.ORIGIN_GROUPS
        ],
    }


class SegmentViewSet(viewsets.ModelViewSet):
    """Deleting a segment keeps its contacts."""

    serializer_class = SegmentSerializer
    permission_classes = [has_capability("manage_recipients")]

    def get_queryset(self):
        return Segment.objects.annotate(count=Count("contacts"))


class ContactPagination(PageNumberPagination):
    page_size = 50


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [has_capability("manage_recipients")]
    pagination_class = ContactPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _filter(self, qs, params):
        """The list's filters, shared with bulk actions on everything
        matching them."""
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(email__icontains=q) | Q(name__icontains=q)
                | Q(company__icontains=q) | Q(phone__icontains=q)
            )
        segment = params.get("segment")
        if segment == "none":
            qs = qs.filter(segments__isnull=True)
        elif segment:
            try:
                qs = qs.filter(segments=int(segment))
            except (TypeError, ValueError):
                raise ValidationError({"detail": "segment must be an id."})
        source = params.get("source")
        if source:
            qs = qs.filter(source=source)
        status = params.get("status")
        if status == "subscribed":
            qs = qs.exclude(email__in=contact_rules.suppressed_emails())
        elif status == "unsubscribed":
            qs = qs.filter(email__in=contact_rules.suppressed_emails())
        return qs

    def get_queryset(self):
        qs = Contact.objects.prefetch_related("segments")
        if self.action == "list":
            qs = self._filter(qs, self.request.query_params)
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        context = self.get_serializer_context()
        context["statuses"] = contact_rules.statuses(c.email for c in page)
        return self.get_paginated_response(
            self.get_serializer(page, many=True, context=context).data
        )

    def perform_create(self, serializer):
        serializer.save(source="manual")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts for the page's side list."""
        suppressed = contact_rules.suppressed_emails()
        return Response({
            "total": Contact.objects.count(),
            "unsubscribed": Contact.objects.filter(email__in=suppressed).count(),
            "unsegmented": Contact.objects.filter(segments__isnull=True).count(),
            "origins": [
                {"key": key, "label": label, "count": Contact.objects.filter(source=key).count()}
                for key, label in contact_rules.ORIGIN_GROUPS
            ],
            "segments": SegmentSerializer(
                Segment.objects.annotate(count=Count("contacts")), many=True
            ).data,
        })

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        """One action on the ticked contacts, or on every contact matching
        the list's filters when all_matching is set."""
        if request.data.get("all_matching"):
            qs = self._filter(Contact.objects.all(), request.data.get("filters") or {})
        else:
            try:
                ids = [int(i) for i in request.data.get("ids") or []]
            except (TypeError, ValueError):
                return Response({"detail": "ids must be numbers."}, status=400)
            qs = Contact.objects.filter(pk__in=ids)
        ids = list(qs.values_list("pk", flat=True))
        if not ids:
            return Response({"detail": "No contacts selected."}, status=400)
        emails = list(Contact.objects.filter(pk__in=ids).values_list("email", flat=True))
        op = request.data.get("action")

        if op in ("add_segment", "remove_segment"):
            segment = Segment.objects.filter(pk=request.data.get("segment") or 0).first()
            if segment is None:
                return Response({"detail": "Choose a segment."}, status=400)
            if op == "add_segment":
                segment.contacts.add(*ids)
            else:
                segment.contacts.remove(*ids)
        elif op == "delete":
            Contact.objects.filter(pk__in=ids).delete()
        elif op == "unsubscribe":
            Suppression.objects.bulk_create(
                [Suppression(email=e, reason="manual") for e in emails], ignore_conflicts=True,
            )
        elif op == "resubscribe":
            # Only undoes a stop staff put in place. People who unsubscribed,
            # bounced or complained themselves stay off the list.
            Suppression.objects.filter(email__in=emails, reason="manual").delete()
        else:
            return Response({"detail": "Unknown action."}, status=400)
        return Response({"count": len(ids)})

    @action(detail=False, methods=["post"], url_path="import")
    def import_contacts(self, request):
        """Add people from a file or pasted text, optionally into segments."""
        upload = request.FILES.get("file")
        if upload:
            if upload.size > MAX_IMPORT_BYTES:
                return Response({"detail": "File too large (max 5MB)."}, status=400)
            try:
                rows = contact_rules.rows_from_file(upload)
            except UnsupportedFileType:
                return Response({"detail": "Use a CSV, TXT, XLSX, PDF or DOCX file."}, status=400)
            except Exception:
                return Response({"detail": "The file could not be read."}, status=400)
        else:
            rows = contact_rules.rows_from_text(request.data.get("text") or "")
        if not rows:
            return Response({"detail": "No email addresses were found."}, status=400)
        segments, error = contact_rules.segment_from_request(request.data)
        if error:
            return Response({"detail": error}, status=400)
        return Response(contact_rules.import_contacts(rows, segments))


class RecipientPagination(PageNumberPagination):
    # Declared explicitly: this project sets no DEFAULT_PAGINATION_CLASS, so
    # without this the endpoint would return every recipient in one response.
    page_size = 50


# Postgres bigint max: the `campaign` FK is a BigAutoField and production runs
# PostgreSQL, so a numeric-looking id beyond this overflows the column and
# raises DataError (500) instead of the intended 400.
POSTGRES_BIGINT_MAX = 9223372036854775807


# A campaign whose record can still be mutated -- recipients added/removed,
# the MX pass re-run. `sent`/`failed` campaigns are history and immutable.
MUTABLE_CAMPAIGN_STATUSES = {"draft", "queued", "sending", "paused"}
DISPATCHED_RECIPIENT_STATUSES = {"sending", "sent", "failed"}


def _parse_campaign_id(value):
    """Parse a campaign id from a query parameter or request-body value.

    Shared by the `campaign` query parameter (list) and the `campaign` body
    field (validate / remove_invalid) so the two can't drift apart: both
    used to be parsed differently, and only the query-parameter path
    defended against a non-numeric or out-of-range id, which crashed the
    body path with a 500 instead of a 400.

    str.isdigit() accepts non-ASCII digit characters (e.g. U+00B2 '²') that
    int() cannot parse, which would raise ValueError (500) instead of the
    intended 400 -- so parse defensively rather than pre-checking digits.
    """
    try:
        numeric_id = int(value)
    except (TypeError, ValueError):
        raise ValidationError({"detail": "campaign must be a numeric id."})
    if numeric_id < 0 or numeric_id > POSTGRES_BIGINT_MAX:
        raise ValidationError({"detail": "campaign must be a numeric id."})
    return numeric_id


def _remove_recipient(recipient):
    """Remove one recipient from its campaign. Returns None on success.

    Behaviour depends on how far the campaign has progressed:
      draft                    -> delete outright and give the slot back
      queued/sending/paused    -> mark skipped; the sender only claims
                                  `pending` rows, so it will never be emailed
      sent/failed              -> refuse; a finished campaign's record is history

    Every successful removal also records a CampaignExclusion for the
    campaign+email so a later `build_recipients` rebuild does not silently
    resurrect the address -- see CampaignExclusion's docstring. A repeat
    removal of the same address must not raise on the unique constraint, so
    this always uses get_or_create.

    On failure, returns the reason as a string for the caller to surface.
    """
    campaign = recipient.campaign
    if campaign.status not in MUTABLE_CAMPAIGN_STATUSES:
        return f"Cannot change recipients of a {campaign.status} campaign."

    if recipient.status in DISPATCHED_RECIPIENT_STATUSES:
        return f"This message is already {recipient.status} and cannot be withdrawn."

    if campaign.status == "draft":
        with transaction.atomic():
            email = recipient.email
            recipient.delete()
            # total is a PositiveIntegerField, so guard the decrement rather
            # than letting a stale counter underflow into a database error.
            Campaign.objects.filter(pk=campaign.pk, total__gt=0).update(
                total=F("total") - 1
            )
            CampaignExclusion.objects.get_or_create(campaign=campaign, email=email)
        return None

    # Guarded UPDATE, mirroring the outbox sender's own claiming pattern
    # (see process_email_outbox.py). recipient.status here is only the
    # value read by get_object() and may be stale: between that read and
    # this write, the sender may have claimed the row (pending -> sending)
    # to send it. Keying the write on `status="pending"` at the database
    # level closes that race -- a claimed row will no longer match and so
    # will not be overwritten to "skipped" out from under the sender.
    updated = CampaignRecipient.objects.filter(
        pk=recipient.pk, status="pending"
    ).update(status="skipped")
    if updated:
        CampaignExclusion.objects.get_or_create(campaign=campaign, email=recipient.email)
        return None

    # Nothing matched pending=... reread to find out why.
    current_status = (
        CampaignRecipient.objects.filter(pk=recipient.pk)
        .values_list("status", flat=True)
        .first()
    )
    if current_status is None or current_status == "skipped":
        # Already gone or already skipped -- removal is idempotent.
        CampaignExclusion.objects.get_or_create(campaign=campaign, email=recipient.email)
        return None
    return "This message is already being sent and cannot be withdrawn."


class CampaignRecipientViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    # Built from explicit mixins rather than ModelViewSet: recipient rows should
    # only be listed, added, and removed via the API. ModelViewSet would also
    # route retrieve/update/partial_update, none of which are requested or
    # tested, plus a destroy with unoverridden semantics (see perform_destroy /
    # a later task for status-dependent removal).
    serializer_class = CampaignRecipientSerializer
    permission_classes = [has_capability("manage_recipients")]
    pagination_class = RecipientPagination

    def get_queryset(self):
        qs = CampaignRecipient.objects.select_related("campaign").order_by("id")

        # Scoping applies to `list` only. get_object() runs this same method for
        # detail routes, where no `campaign` query parameter is present -- making
        # it mandatory there would break DELETE.
        if self.action != "list":
            return qs

        campaign_id = self.request.query_params.get("campaign")
        if not campaign_id:
            raise ValidationError({"detail": "A campaign query parameter is required."})
        numeric_campaign_id = _parse_campaign_id(campaign_id)
        qs = qs.filter(campaign_id=numeric_campaign_id)

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(email__icontains=search) | Q(name__icontains=search))
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            recipient = serializer.save()
            # A manual add is the admin overriding an earlier removal of this
            # exact address -- clear the exclusion in the same transaction as
            # the insert so a later rebuild doesn't drop the address again.
            CampaignExclusion.objects.filter(
                campaign_id=recipient.campaign_id, email=recipient.email
            ).delete()
            # Re-assert the campaign's status atomically with the insert:
            # `serializer.validate()` already checked it, but that read
            # happened before this transaction started. Between then and
            # here, the outbox sender's `_maybe_complete` could have flipped
            # the campaign to `sent` (it only scans queued/sending
            # campaigns), which would otherwise strand this row -- inserted,
            # counted in `total`, but never sent. Guard the increment on
            # status the same way `_remove_recipient` guards its update; if
            # nothing matches, roll back the whole transaction, including
            # the insert.
            updated = Campaign.objects.filter(
                pk=recipient.campaign_id, status__in=ADDABLE_CAMPAIGN_STATUSES
            ).update(total=F("total") + 1)
            if not updated:
                raise ValidationError(
                    {"detail": "This campaign finished before the recipient could be added."}
                )

    def destroy(self, request, *args, **kwargs):
        recipient = self.get_object()
        error = _remove_recipient(recipient)
        if error:
            return Response({"detail": error}, status=400)
        return Response(status=204)

    def _campaign_from_body(self, request):
        campaign_id = request.data.get("campaign")
        # `campaign_id` may legitimately be 0 (falsy) -- distinguish "absent"
        # from "present but zero" so {"campaign": 0} 404s instead of being
        # reported as missing.
        if campaign_id is None or campaign_id == "":
            raise ValidationError({"detail": "A campaign id is required."})
        numeric_campaign_id = _parse_campaign_id(campaign_id)
        return get_object_or_404(Campaign, pk=numeric_campaign_id)

    @action(detail=False, methods=["post"])
    def validate(self, request):
        """Run the MX pass over one campaign and report the resulting counts.

        Deliberately an explicit action rather than part of building the
        audience: DNS is slow, and a list spanning many domains would otherwise
        stall the build request.
        """
        campaign = self._campaign_from_body(request)
        if campaign.status not in MUTABLE_CAMPAIGN_STATUSES:
            return Response(
                {"detail": f"Cannot change recipients of a {campaign.status} campaign."},
                status=400,
            )
        return Response(validate_campaign_recipients(campaign))

    @action(detail=False, methods=["post"])
    def remove_invalid(self, request):
        """Remove every flagged recipient, honouring the usual removal rules.

        Set-based rather than a per-row loop over `_remove_recipient`: a
        campaign with thousands of flagged rows would otherwise cost
        thousands of round trips (a DELETE plus a Campaign update per draft
        row, or a guarded UPDATE plus a re-read per non-draft row), each in
        its own tiny transaction. This does the same work in a handful of
        queries, all inside one transaction, so a partial failure can't
        leave rows removed with `total` left un-decremented.

        Also records a CampaignExclusion for every row actually removed or
        marked skipped, in bulk, for the same reason `_remove_recipient`
        does for a single row: without it, a later rebuild would resurrect
        these addresses. `ignore_conflicts=True` makes a repeat run safe.
        """
        campaign = self._campaign_from_body(request)
        if campaign.status not in MUTABLE_CAMPAIGN_STATUSES:
            return Response(
                {"detail": f"Cannot change recipients of a {campaign.status} campaign."},
                status=400,
            )

        flagged = CampaignRecipient.objects.filter(
            campaign=campaign,
            validation_status__in=["invalid_syntax", "invalid_domain"],
        )

        with transaction.atomic():
            # Rows already dispatched (sending/sent/failed) are refused
            # outright, same as `_remove_recipient` -- never deleted, never
            # re-marked, always reported as skipped.
            skipped = flagged.filter(status__in=DISPATCHED_RECIPIENT_STATUSES).count()

            if campaign.status == "draft":
                # Eligible rows -- flagged and not dispatched -- are deleted
                # outright. This includes rows already `skipped`: a draft
                # campaign has no in-flight send to protect.
                eligible = flagged.exclude(status__in=DISPATCHED_RECIPIENT_STATUSES)
                # Emails must be captured before the delete empties the queryset.
                removed_emails = list(eligible.values_list("email", flat=True))
                removed, _deleted_by_model = eligible.delete()
                if removed:
                    # total is a PositiveIntegerField -- only decrement if
                    # enough headroom exists, mirroring the per-row guard
                    # this replaces so it can never go negative.
                    Campaign.objects.filter(pk=campaign.pk, total__gte=removed).update(
                        total=F("total") - removed
                    )
                    CampaignExclusion.objects.bulk_create(
                        [CampaignExclusion(campaign=campaign, email=e) for e in removed_emails],
                        ignore_conflicts=True,
                    )
            else:
                # Queued/sending/paused: flag pending rows as skipped via a
                # single guarded UPDATE (the sender only claims `pending`
                # rows, so this is race-safe the same way the single-row
                # helper's guarded UPDATE is). Rows already skipped count as
                # successfully removed -- removal is idempotent.
                already_skipped_emails = list(
                    flagged.filter(status="skipped").values_list("email", flat=True)
                )
                pending = flagged.filter(status="pending")
                pending_emails = list(pending.values_list("email", flat=True))
                updated = pending.update(status="skipped")
                removed = updated + len(already_skipped_emails)
                exclusion_emails = set(already_skipped_emails) | set(pending_emails)
                if exclusion_emails:
                    CampaignExclusion.objects.bulk_create(
                        [CampaignExclusion(campaign=campaign, email=e) for e in exclusion_emails],
                        ignore_conflicts=True,
                    )

        return Response({"removed": removed, "skipped": skipped})


from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser

from .imports import extract_emails_from_file, UnsupportedFileType

MAX_IMPORT_BYTES = 5 * 1024 * 1024


@api_view(["POST"])
@permission_classes([has_capability("manage_campaigns")])
@parser_classes([MultiPartParser])
def extract_emails(request):
    upload = request.FILES.get("file")
    if not upload:
        return Response({"detail": "No file provided."}, status=400)
    if upload.size > MAX_IMPORT_BYTES:
        return Response({"detail": "File too large (max 5MB)."}, status=400)
    try:
        emails = extract_emails_from_file(upload)
    except UnsupportedFileType:
        return Response({"detail": "Unsupported file type."}, status=400)
    except Exception:
        return Response({"detail": "Could not parse file."}, status=400)
    return Response({"emails": emails, "count": len(emails)})


from .emailhtml import inline_email_css, sanitize_email_html
from .placeholders import PLACEHOLDERS, sample_context, unknown_placeholders
from .rendering import render_html, render_text


@api_view(["GET"])
@permission_classes([has_capability("manage_campaigns")])
def placeholders(request):
    """Registry that drives the editor's insert-placeholder menu."""
    return Response(PLACEHOLDERS)


@api_view(["POST"])
@permission_classes([has_capability("manage_campaigns")])
def preview(request):
    """Render a draft exactly the way the sender will, using sample values."""
    subject_source = request.data.get("subject") or ""
    body_source = request.data.get("body_source") or ""

    context = sample_context()
    prepared_html = inline_email_css(sanitize_email_html(body_source))

    unknown = []
    for text in (subject_source, body_source):
        for key in unknown_placeholders(text):
            if key not in unknown:
                unknown.append(key)

    return Response({
        "subject": render_text(subject_source, context),
        "body_html": render_html(prepared_html, context),
        "unknown": unknown,
    })
