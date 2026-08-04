from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse


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


def capability_required_api(codename):
    """Require a named capability on a JSON endpoint.

    Same rule as capability_required, but it answers with JSON instead of a
    login redirect or an HTML 403. Fetch follows redirects transparently, so
    the HTML variant made a permissions problem reach the browser as a login
    page that then failed to parse as JSON -- the caller saw "Unexpected
    token '<'" and no indication that permissions were the cause.

    Mirrors the response shape of brand.api_views.capability_required_json,
    which does the same job for the panel's function-style API views.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return JsonResponse({"error": "Unauthorized"}, status=401)
            if not (user.is_staff and user.has_perm(f"staff.{codename}")):
                return JsonResponse({"error": "Forbidden"}, status=403)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
