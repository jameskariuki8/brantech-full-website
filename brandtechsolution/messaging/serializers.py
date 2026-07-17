from rest_framework import serializers
from .models import Inquiry


class InquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = ["id", "name", "email", "phone", "message", "status", "created_at"]
        read_only_fields = ["id", "name", "email", "phone", "message", "created_at"]
