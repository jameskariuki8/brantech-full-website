from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api

router = DefaultRouter()
router.register(r"inquiries", api.InquiryViewSet, basename="inquiries")

urlpatterns = [
    path("", include(router.urls)),
]
