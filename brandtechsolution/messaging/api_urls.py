from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api, mail_api

router = DefaultRouter()
router.register(r"inquiries", api.InquiryViewSet, basename="inquiries")
router.register(r"templates", api.EmailTemplateViewSet, basename="templates")
router.register(r"campaigns", api.CampaignViewSet, basename="campaigns")
router.register(r"recipients", api.CampaignRecipientViewSet, basename="recipients")
router.register(r"contacts", api.ContactViewSet, basename="contacts")
router.register(r"segments", api.SegmentViewSet, basename="segments")

urlpatterns = [
    path("", include(router.urls)),
    path("extract-emails/", api.extract_emails, name="extract-emails"),
    path("placeholders/", api.placeholders, name="placeholders"),
    path("preview/", api.preview, name="preview"),
    path("mail/mailboxes/", mail_api.mailboxes, name="mail-mailboxes"),
    path("mail/unread/", mail_api.unread_count, name="mail-unread"),
    path("mail/threads/", mail_api.threads, name="mail-threads"),
    path("mail/threads/<int:pk>/", mail_api.thread_detail, name="mail-thread"),
    path("mail/threads/<int:pk>/state/", mail_api.thread_state, name="mail-thread-state"),
    path("mail/threads/<int:pk>/reply/", mail_api.reply, name="mail-reply"),
    path("mail/threads/<int:pk>/delete/", mail_api.delete_thread, name="mail-delete"),
    path("mail/compose/", mail_api.compose, name="mail-compose"),
    path("mail/limits/", mail_api.limits, name="mail-limits"),
    path("mail/limits/people/<int:pk>/", mail_api.person_limit, name="mail-person-limit"),
]
