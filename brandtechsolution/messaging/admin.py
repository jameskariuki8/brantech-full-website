from django.contrib import admin
from .models import InboundEmail, Inquiry, EmailTemplate, Campaign, Suppression

@admin.register(InboundEmail)
class InboundEmailAdmin(admin.ModelAdmin):
    list_display = ("sender", "recipient", "subject", "status", "received_at")
    list_filter = ("status", "received_at")
    search_fields = ("sender", "recipient", "subject", "body_plain")

@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "email", "message")

