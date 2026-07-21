from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .audit import record
from .capabilities import CAPABILITY_GROUPS
from .permissions import has_capability
from .serializers import RoleSerializer


class StaffPagination(PageNumberPagination):
    page_size = 50


@api_view(["GET"])
@permission_classes([has_capability("manage_staff")])
def capabilities(request):
    """The capability registry, grouped as the UI displays it."""
    return Response([
        {
            "label": label,
            "capabilities": [
                {"codename": codename, "label": text} for codename, text in pairs
            ],
        }
        for label, pairs in CAPABILITY_GROUPS
    ])


class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        return Group.objects.annotate(member_count=Count("user")).order_by("name")

    def _codenames(self, group):
        return sorted(
            group.permissions.filter(
                content_type__app_label="staff"
            ).values_list("codename", flat=True)
        )

    def perform_create(self, serializer):
        with transaction.atomic():
            group = serializer.save()
            record(
                actor=self.request.user,
                action="group_created",
                summary=f"{self.request.user} created the role {group.name}",
                target_group=group,
                detail={"after": self._codenames(group)},
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            before = self._codenames(serializer.instance)
            group = serializer.save()
            record(
                actor=self.request.user,
                action="group_updated",
                summary=f"{self.request.user} changed the role {group.name}",
                target_group=group,
                detail={"before": before, "after": self._codenames(group)},
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            name = instance.name
            codenames = self._codenames(instance)
            record(
                actor=self.request.user,
                action="group_deleted",
                summary=f"{self.request.user} deleted the role {name}",
                detail={"before": codenames, "name": name},
            )
            instance.delete()
