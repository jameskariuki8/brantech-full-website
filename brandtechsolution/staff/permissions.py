from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


def enforce_grantable_roles(actor, roles):
    """Raise PermissionDenied if `actor` is granting a role carrying a
    capability they do not hold themselves.

    A non-superuser may only grant capabilities they already possess -
    otherwise they could hand out (or claim, via an invitation to their own
    second address) capabilities beyond their own standing. Superusers are
    exempt: has_perm() already returns True for them unconditionally, so the
    check would be a no-op, but the exemption is spelled out here rather
    than left incidental.

    `roles` should be the set of roles being newly added (e.g. group
    membership being granted), not the full set a target ends up with -
    removing a role is de-escalation and is never restricted by this check.

    Shared by PersonViewSet.perform_update (granting roles to an existing
    account) and InvitationViewSet.perform_create (inviting someone with
    roles is a grant too, made before any account exists).

    EVERY permission on the role is checked, not only this app's
    capabilities. An auth.Group can carry any Django permission, and any
    group made through /admin/ before this feature existed probably does.
    Filtering to app_label="staff" left those completely unrestricted, which
    was a path from manage_staff to is_superuser: grant a role carrying
    auth.change_user, accept it on an account you control, then tick
    is_superuser in /admin/, which exposes that field to anyone holding
    change_user. The capability registry is not the boundary - the actor's
    own standing is.
    """
    if actor.is_superuser:
        return
    for role in roles:
        held_by_role = role.permissions.select_related("content_type")
        for permission in held_by_role:
            label = f"{permission.content_type.app_label}.{permission.codename}"
            if not actor.has_perm(label):
                raise PermissionDenied(
                    f"You cannot grant the '{role.name}' role: it "
                    f"includes the '{label}' permission, which "
                    "you do not hold yourself."
                )


def has_capability(codename):
    """Build a DRF permission class requiring one named capability.

    Usage:
        permission_classes = [has_capability("manage_campaigns")]

    is_staff is required in addition to the capability: the panel is not for
    ordinary signed-up accounts, and /signup/ is public. Superusers pass
    because has_perm() returns True for them unconditionally.
    """

    class _HasCapability(BasePermission):
        message = f"This action requires the '{codename}' capability."

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated and user.is_staff):
                return False
            return user.has_perm(f"staff.{codename}")

    _HasCapability.__name__ = f"HasCapability_{codename}"
    return _HasCapability
