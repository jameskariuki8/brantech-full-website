from django.contrib import admin
from approval.models import ApprovalNotification


@admin.register(ApprovalNotification)
class ApprovalNotificationAdmin(admin.ModelAdmin):
    list_display = ('article', 'channel', 'recipient', 'is_sent', 'sent_at')
    list_filter = ('channel', 'is_sent')
