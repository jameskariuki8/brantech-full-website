from rest_framework.permissions import BasePermission


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
