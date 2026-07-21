from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register(r"roles", api.RoleViewSet, basename="roles")

urlpatterns = [
    path("", include(router.urls)),
    path("capabilities/", api.capabilities, name="capabilities"),
]
