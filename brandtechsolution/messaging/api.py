from django.db import transaction
from django.db.models import F, Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from . import audience
from .models import Campaign, CampaignRecipient, EmailTemplate, Inquiry
from .serializers import (
    CampaignRecipientSerializer,
    CampaignSerializer,
    EmailTemplateSerializer,
    InquirySerializer,
)


class InquiryViewSet(viewsets.ModelViewSet):
    queryset = Inquiry.objects.all()
    serializer_class = InquirySerializer
    permission_classes = [IsAdminUser]


class EmailTemplateViewSet(viewsets.ModelViewSet):
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer
    permission_classes = [IsAdminUser]


class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer
    permission_classes = [IsAdminUser]

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


REMOVABLE_CAMPAIGN_STATUSES = {"draft", "queued", "sending", "paused"}
DISPATCHED_RECIPIENT_STATUSES = {"sending", "sent", "failed"}


def _remove_recipient(recipient):
    """Remove one recipient from its campaign. Returns None on success.

    Behaviour depends on how far the campaign has progressed:
      draft                    -> delete outright and give the slot back
      queued/sending/paused    -> mark skipped; the sender only claims
                                  `pending` rows, so it will never be emailed
      sent/failed              -> refuse; a finished campaign's record is history

    On failure, returns the reason as a string for the caller to surface.
    """
    campaign = recipient.campaign
    if campaign.status not in REMOVABLE_CAMPAIGN_STATUSES:
        return f"Cannot change recipients of a {campaign.status} campaign."

    if recipient.status in DISPATCHED_RECIPIENT_STATUSES:
        return f"This message is already {recipient.status} and cannot be withdrawn."

    if campaign.status == "draft":
        with transaction.atomic():
            recipient.delete()
            # total is a PositiveIntegerField, so guard the decrement rather
            # than letting a stale counter underflow into a database error.
            Campaign.objects.filter(pk=campaign.pk, total__gt=0).update(
                total=F("total") - 1
            )
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
        return None

    # Nothing matched pending=... reread to find out why.
    current_status = (
        CampaignRecipient.objects.filter(pk=recipient.pk)
        .values_list("status", flat=True)
        .first()
    )
    if current_status is None or current_status == "skipped":
        # Already gone or already skipped -- removal is idempotent.
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
    permission_classes = [IsAdminUser]
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
        # str.isdigit() accepts non-ASCII digit characters (e.g. U+00B2 '²')
        # that int() cannot parse, which would raise ValueError (500) instead
        # of the intended 400. Parse defensively so int() is never reached
        # with a value it can't handle.
        try:
            numeric_campaign_id = int(campaign_id)
        except (TypeError, ValueError):
            raise ValidationError({"detail": "campaign must be a numeric id."})
        if numeric_campaign_id < 0 or numeric_campaign_id > POSTGRES_BIGINT_MAX:
            raise ValidationError({"detail": "campaign must be a numeric id."})
        qs = qs.filter(campaign_id=campaign_id)

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(email__icontains=search) | Q(name__icontains=search))
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            recipient = serializer.save()
            Campaign.objects.filter(pk=recipient.campaign_id).update(total=F("total") + 1)

    def destroy(self, request, *args, **kwargs):
        recipient = self.get_object()
        error = _remove_recipient(recipient)
        if error:
            return Response({"detail": error}, status=400)
        return Response(status=204)


from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser

from .imports import extract_emails_from_file, UnsupportedFileType

MAX_IMPORT_BYTES = 5 * 1024 * 1024


@api_view(["POST"])
@permission_classes([IsAdminUser])
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
@permission_classes([IsAdminUser])
def placeholders(request):
    """Registry that drives the editor's insert-placeholder menu."""
    return Response(PLACEHOLDERS)


@api_view(["POST"])
@permission_classes([IsAdminUser])
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
