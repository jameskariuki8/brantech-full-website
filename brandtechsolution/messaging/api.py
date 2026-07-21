from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from staff.permissions import has_capability

from . import audience
from .models import Campaign, CampaignExclusion, CampaignRecipient, EmailTemplate, Inquiry
from .serializers import (
    ADDABLE_CAMPAIGN_STATUSES,
    CampaignRecipientSerializer,
    CampaignSerializer,
    EmailTemplateSerializer,
    InquirySerializer,
)
from .validation import validate_campaign_recipients


class InquiryViewSet(viewsets.ModelViewSet):
    queryset = Inquiry.objects.all()
    serializer_class = InquirySerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [has_capability("view_inbox")()]
        return [has_capability("handle_inquiries")()]


class EmailTemplateViewSet(viewsets.ModelViewSet):
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer
    permission_classes = [has_capability("manage_templates")]


class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer

    # Sending is the one irreversible, externally visible action, so it is
    # gated separately from ordinary campaign editing.
    ACTION_CAPABILITIES = {
        "build_recipients": "manage_recipients",
        "queue": "send_campaigns",
        "pause": "send_campaigns",
        "resume": "send_campaigns",
    }

    def get_permissions(self):
        capability = self.ACTION_CAPABILITIES.get(self.action, "manage_campaigns")
        return [has_capability(capability)()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

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
        count = audience.build_recipients(campaign, sources, manual)
        return Response({"count": count})

    @action(detail=True, methods=["post"])
    def queue(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != "draft":
            return Response({"detail": "Only draft campaigns can be queued."}, status=400)
        if campaign.total == 0:
            return Response({"detail": "No recipients. Build recipients first."}, status=400)
        campaign.status = "queued"
        campaign.save(update_fields=["status"])
        return Response({"status": campaign.status})

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
        campaign.save(update_fields=["status"])
        return Response({"status": campaign.status})


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
