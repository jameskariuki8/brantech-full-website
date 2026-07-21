from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .audit import record
from .capabilities import CAPABILITY_GROUPS
from .emails import send_invitation
from .models import StaffInvitation
from .permissions import enforce_grantable_roles, has_capability
from .serializers import InvitationSerializer, PersonSerializer, RoleSerializer


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

        # The site currently has exactly one superuser: the owner. Without
        # this check, anyone delegated manage_staff could reassign the
        # owner's roles or deactivate their account and lock them out of
        # their own site. Superusers remain the escape hatch and can manage
        # each other (including themselves) freely.
        if target.is_superuser and not actor.is_superuser:
            raise PermissionDenied(
                "You cannot change a superuser's roles or active state."
            )

        # An actor may only grant capabilities they already hold. Only
        # additions are checked - removing a role is de-escalation and stays
        # unrestricted, so an admin can still clean up an account even if
        # they don't personally hold every capability being stripped.
        if "groups" in serializer.validated_data:
            current_roles = set(target.groups.all())
            new_roles = set(serializer.validated_data["groups"])
            enforce_grantable_roles(actor, new_roles - current_roles)

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


class InvitationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = InvitationSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        return StaffInvitation.objects.filter(
            accepted_at__isnull=True
        ).prefetch_related("groups")

    def perform_create(self, serializer):
        # Inviting someone with roles is a grant, made before any account
        # exists: without this check a manage_staff holder could invite a
        # second address of their own carrying the Administrator role and
        # accept that invitation themselves, trivially escalating past the
        # same restriction PersonViewSet.perform_update enforces on existing
        # accounts. Checked before serializer.save() so a forbidden request
        # never creates the invitation row.
        roles = serializer.validated_data.get("groups", [])
        enforce_grantable_roles(self.request.user, roles)

        with transaction.atomic():
            invitation = serializer.save(invited_by=self.request.user)
            record(
                actor=self.request.user,
                action="invite_sent",
                summary=f"{self.request.user} invited {invitation.email}",
                detail={"email": invitation.email,
                        "roles": sorted(g.name for g in invitation.groups.all())},
            )
        # Deliberately outside the transaction, and deliberately NOT rolling
        # it back on failure: if the mail server is down we keep the
        # invitation row so it can be resent, rather than losing it. The
        # trade-off is that the audit entry can outlive a send that failed,
        # so the failure is recorded too instead of surfacing as a 500.
        try:
            send_invitation(invitation, self.request)
        except Exception:
            record(
                actor=self.request.user,
                action="invite_send_failed",
                summary=(
                    f"Invitation email to {invitation.email} could not be sent"
                ),
                detail={"email": invitation.email},
            )

    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        """Send a fresh link for an invitation that is still pending.

        No model change is needed: tokens are signed with a timestamp at
        generation, so a newly minted token carries a full 7-day window on
        its own. get_queryset() already excludes accepted invitations, so an
        accepted one 404s here rather than re-opening a closed account.
        """
        invitation = self.get_object()

        # The address may have been registered through the public /signup/
        # page since the invitation was issued, in which case accepting it
        # cannot succeed - so resending would only mail a link that dead-ends.
        if User.objects.filter(
            Q(username__iexact=invitation.email) | Q(email__iexact=invitation.email)
        ).exists():
            raise ValidationError(
                "An account now exists for this address. Revoke this invitation "
                "and edit that person's roles instead."
            )

        send_invitation(invitation, request)
        record(
            actor=request.user,
            action="invite_resent",
            summary=f"{request.user} resent the invitation to {invitation.email}",
            detail={"email": invitation.email},
        )
        return Response({"status": "sent"})

    def perform_destroy(self, instance):
        with transaction.atomic():
            record(
                actor=self.request.user,
                action="invite_revoked",
                summary=f"{self.request.user} revoked the invitation to {instance.email}",
                detail={"email": instance.email},
            )
            instance.delete()
