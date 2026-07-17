from rest_framework import serializers
from .models import EmailTemplate, Inquiry


class InquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = ["id", "name", "email", "phone", "message", "status", "created_at"]
        read_only_fields = ["id", "name", "email", "phone", "message", "created_at"]


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ["id", "name", "subject", "body_html", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
