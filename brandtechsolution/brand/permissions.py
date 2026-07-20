from rest_framework.permissions import SAFE_METHODS, BasePermission


class StaffWriteOrReadOnly(BasePermission):
    """Anyone may read; only staff may write.

    The public blog and projects pages fetch these endpoints to render their
    listings, so reads stay open to anonymous visitors. Creating, editing and
    deleting site content is administrative.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(user and user.is_authenticated and user.is_staff)
