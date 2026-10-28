from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api, webhooks

router = DefaultRouter()
router.register(r"tasks", api.TaskViewSet, basename="tasks")
router.register(r"repos", api.RepositoryViewSet, basename="task-repos")

urlpatterns = [
    path("github/webhook/", webhooks.github_webhook, name="task-github-webhook"),
    path("", include(router.urls)),
    path("backlog-projects/", api.backlog_projects, name="task-backlog-projects"),
    path("summary/", api.summary, name="task-summary"),
    path("assignable/", api.assignable, name="task-assignable"),
]
