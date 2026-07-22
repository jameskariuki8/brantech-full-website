from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def capability_required(codename, login_url="/login/"):
    """Require a named capability on a plain Django view.

    Anonymous users are redirected to the login page, matching the existing
    behaviour of the panel's login_required gates. A signed-in user who lacks
    the capability gets a 403 rather than a redirect, because bouncing an
    already-authenticated user to a login form is a dead end.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path(), login_url)
            if not (user.is_staff and user.has_perm(f"staff.{codename}")):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
