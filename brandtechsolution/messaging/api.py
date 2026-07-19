from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from . import audience
from .models import Campaign, EmailTemplate, Inquiry
from .serializers import CampaignSerializer, EmailTemplateSerializer, InquirySerializer


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
