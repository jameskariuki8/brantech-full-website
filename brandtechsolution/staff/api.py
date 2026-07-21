from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Count
from rest_framework import mixins, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .audit import record
from .capabilities import CAPABILITY_GROUPS
from .permissions import has_capability
from .serializers import PersonSerializer, RoleSerializer


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


class PersonViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Staff accounts. Creation happens through invitations, not here."""

    serializer_class = PersonSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        return User.objects.filter(is_staff=True).prefetch_related("groups").order_by(
            "username"
        )

    def perform_update(self, serializer):
        actor = self.request.user
        target = serializer.instance

        # A non-superuser editing themselves could drop manage_staff or switch
        # off their own account and lock the panel. One flat rule beats
        # last-admin-standing arithmetic; superusers remain the escape hatch.
        if target.pk == actor.pk and not actor.is_superuser:
            raise PermissionDenied(
                "You cannot change your own roles or deactivate your own account."
            )

        with transaction.atomic():
            before_roles = sorted(g.name for g in target.groups.all())
            was_active = target.is_active
            person = serializer.save()
            after_roles = sorted(g.name for g in person.groups.all())

            if after_roles != before_roles:
                record(
                    actor=actor,
                    action="roles_changed",
                    summary=(
                        f"{actor} changed {person}'s roles to "
                        f"{', '.join(after_roles) or 'none'}"
                    ),
                    target_user=person,
                    detail={"before": before_roles, "after": after_roles},
                )

            if person.is_active != was_active:
                action = "user_reactivated" if person.is_active else "user_deactivated"
                verb = "reactivated" if person.is_active else "deactivated"
                record(
                    actor=actor,
                    action=action,
                    summary=f"{actor} {verb} {person}",
                    target_user=person,
                )
