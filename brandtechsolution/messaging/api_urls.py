from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api

router = DefaultRouter()
router.register(r"inquiries", api.InquiryViewSet, basename="inquiries")
router.register(r"templates", api.EmailTemplateViewSet, basename="templates")
router.register(r"campaigns", api.CampaignViewSet, basename="campaigns")

urlpatterns = [
    path("", include(router.urls)),
    path("extract-emails/", api.extract_emails, name="extract-emails"),
]
