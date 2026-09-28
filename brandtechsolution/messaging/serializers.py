from rest_framework import serializers

from .emailhtml import inline_email_css, sanitize_email_html
from .models import Campaign, CampaignRecipient, Contact, EmailTemplate, Inquiry, Segment, Suppression
from . import campaigns as campaign_rules
from . import contacts as contact_rules
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
    used_by = serializers.SerializerMethodField()

    class Meta:
        model = EmailTemplate
        fields = [
            "id", "name", "subject", "body_source", "body_html",
            "created_at", "updated_at", "used_by",
        ]
        read_only_fields = ["id", "body_html", "created_at", "updated_at"]

    def get_used_by(self, obj):
        return obj.campaign_set.count()

    def update(self, instance, validated_data):
        template = super().update(instance, validated_data)
        campaign_rules.refresh_drafts(template)
        return template


class CampaignSerializer(EmailBodyMixin, serializers.ModelSerializer):
    """A campaign normally takes its content from a template. A body may
    still be given directly, which is how campaigns were made before
    templates and campaigns were split, but one or the other is required."""

    body_source = serializers.CharField(allow_blank=False, required=False)
    subject = serializers.CharField(max_length=255, required=False)
    template_name = serializers.CharField(source="template.name", read_only=True, default="")
    from_address = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    # Only a draft can be edited; after queueing these are history.
    DRAFT_ONLY = ("template", "subject", "body_source", "from_mailbox")

    class Meta:
        model = Campaign
        fields = [
            "id", "name", "subject", "body_source", "body_html", "template",
            "template_name", "from_mailbox", "from_address", "send_at", "note", "audience",
            "status", "total", "sent_count", "failed_count", "stats",
            "created_by_name", "created_at", "started_at", "completed_at",
        ]
        read_only_fields = [
            "id", "body_html", "send_at", "note", "audience", "status", "total", "sent_count",
            "failed_count", "created_at", "started_at", "completed_at",
        ]

    def get_from_address(self, obj):
        return campaign_rules.from_header(obj)

    def get_created_by_name(self, obj):
        user = obj.created_by
        return (user.get_full_name() or user.username) if user else ""

    def get_stats(self, obj):
        rows = obj.recipients.values_list("status", "outcome")
        stats = {"pending": 0, "sent": 0, "failed": 0, "skipped": 0,
                 "delivered": 0, "bounced": 0, "complained": 0}
        for status, outcome in rows:
            key = "pending" if status == "sending" else status
            stats[key] = stats.get(key, 0) + 1
            if outcome:
                stats[outcome] += 1
        return stats

    def validate_from_mailbox(self, value):
        user = self.context["request"].user
        if value and not campaign_rules.allowed_sender(user, value, self.instance):
            raise serializers.ValidationError("You cannot send from that address.")
        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.status != "draft":
            locked = [f for f in self.DRAFT_ONLY if f in attrs]
            if locked:
                raise serializers.ValidationError(
                    {"detail": "Only a draft campaign's email and sender can be changed."}
                )
        if self.instance is None and not attrs.get("template") and not attrs.get("body_source"):
            raise serializers.ValidationError({"template": "Choose a template."})
        if self.instance is None and not attrs.get("template") and not attrs.get("subject"):
            raise serializers.ValidationError({"subject": "This field is required."})
        return attrs

    def _with_template(self, validated_data):
        template = validated_data.get("template")
        if template is not None:
            validated_data["subject"] = template.subject
            validated_data["body_source"] = template.body_source
            validated_data["body_html"] = template.body_html
        return validated_data

    def create(self, validated_data):
        validated_data.setdefault("from_mailbox", "hello")
        return super().create(self._with_template(validated_data))

    def update(self, instance, validated_data):
        return super().update(instance, self._with_template(validated_data))


class SegmentSerializer(serializers.ModelSerializer):
    count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Segment
        fields = ["id", "name", "description", "count", "created_at"]
        read_only_fields = ["id", "count", "created_at"]

    def validate_name(self, value):
        value = value.strip()
        clash = Segment.objects.filter(name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("There is already a segment with that name.")
        return value


class ContactSerializer(serializers.ModelSerializer):
    # Declared without the model's UniqueValidator, which would compare the
    # address before it is lowercased; validate_email checks instead.
    email = serializers.EmailField(max_length=254)
    segments = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Segment.objects.all(), required=False
    )
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    status = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            "id", "email", "name", "phone", "company", "notes", "segments",
            "source", "source_label", "status", "status_label", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "source", "created_at", "updated_at"]

    def validate_email(self, value):
        value = contact_rules.normalise(value)
        if contact_rules.is_ours(value):
            raise serializers.ValidationError("That is one of our own addresses.")
        clash = Contact.objects.filter(email=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("There is already a contact with that address.")
        return value

    def _status(self, obj):
        known = self.context.get("statuses")
        if known is not None:
            return known.get(obj.email, "")
        return contact_rules.statuses([obj.email]).get(obj.email, "")

    def get_status(self, obj):
        return self._status(obj) or "subscribed"

    def get_status_label(self, obj):
        return contact_rules.STATUS_LABELS.get(self._status(obj), "Unsubscribed")


ADDABLE_CAMPAIGN_STATUSES = {"draft", "queued", "sending", "paused"}


class CampaignRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignRecipient
        fields = [
            "id", "campaign", "email", "name", "status",
            "validation_status", "validated_at", "sent_at", "outcome", "outcome_detail", "error",
        ]
        read_only_fields = [
            "id", "status", "validation_status", "validated_at", "sent_at",
            "outcome", "outcome_detail", "error",
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
