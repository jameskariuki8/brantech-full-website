from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register(r"tasks", api.TaskViewSet, basename="tasks")

urlpatterns = [
    path("", include(router.urls)),
    path("summary/", api.summary, name="task-summary"),
    path("assignable/", api.assignable, name="task-assignable"),
]
