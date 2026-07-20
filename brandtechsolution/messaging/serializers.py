from rest_framework import serializers

from .emailhtml import inline_email_css, sanitize_email_html
from .models import Campaign, CampaignRecipient, EmailTemplate, Inquiry, Suppression
from .validation import validate_syntax


class InquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = ["id", "name", "email", "phone", "message", "status", "created_at"]
        read_only_fields = ["id", "name", "email", "phone", "message", "created_at"]


class EmailBodyMixin(serializers.Serializer):
    """Sanitize the authored body and derive the inlined body sent to recipients.

    Clients submit `body_source`; `body_html` is always derived, never accepted.

    Inherits from `serializers.Serializer` (rather than being a plain mixin)
    so that DRF's `SerializerMetaclass` picks up the `body_source` declared
    field into `_declared_fields` and propagates it to subclasses; a plain
    class attribute is invisible to that machinery and would be silently
    replaced by the model-inferred field (`required=False, allow_blank=True`).
    """

    body_source = serializers.CharField(allow_blank=False)

    def validate_body_source(self, value):
        return sanitize_email_html(value)

    def _with_derived_body(self, validated_data):
        if "body_source" in validated_data:
            validated_data["body_html"] = inline_email_css(validated_data["body_source"])
        return validated_data

    def create(self, validated_data):
        return super().create(self._with_derived_body(validated_data))

    def update(self, instance, validated_data):
        return super().update(instance, self._with_derived_body(validated_data))


class EmailTemplateSerializer(EmailBodyMixin, serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = [
            "id", "name", "subject", "body_source", "body_html",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "body_html", "created_at", "updated_at"]


class CampaignSerializer(EmailBodyMixin, serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "id", "name", "subject", "body_source", "body_html", "template", "status",
            "total", "sent_count", "failed_count",
            "created_at", "started_at", "completed_at",
        ]
        read_only_fields = [
            "id", "body_html", "status", "total", "sent_count", "failed_count",
            "created_at", "started_at", "completed_at",
        ]


ADDABLE_CAMPAIGN_STATUSES = {"draft", "queued", "sending", "paused"}


class CampaignRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignRecipient
        fields = [
            "id", "campaign", "email", "name", "status",
            "validation_status", "validated_at", "sent_at",
        ]
        read_only_fields = [
            "id", "status", "validation_status", "validated_at", "sent_at",
        ]

    def validate_email(self, value):
        # Match how audience.resolve_recipients() stores addresses, so the
        # unique_together check and the send path see the same string.
        return (value or "").strip().lower()

    def validate(self, attrs):
        campaign = attrs.get("campaign")
        if campaign and campaign.status not in ADDABLE_CAMPAIGN_STATUSES:
            raise serializers.ValidationError(
                {"detail": f"Cannot add recipients to a {campaign.status} campaign."}
            )

        email = attrs.get("email")
        if email and Suppression.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                {"detail": f"{email} has unsubscribed or bounced and cannot be added."}
            )
        return attrs

    def create(self, validated_data):
        validated_data["validation_status"] = (
            "valid" if validate_syntax(validated_data["email"]) else "invalid_syntax"
        )
        return super().create(validated_data)
