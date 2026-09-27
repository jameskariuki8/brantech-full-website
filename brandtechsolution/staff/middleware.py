from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from .handles import needs_handle

# The HTML pages of the panel. APIs are left alone: a page that never
# loads cannot call them, and a 302 would only confuse fetch().
GATED_PREFIXES = ("/admin-panel/", "/appointments/", "/editorial/")


class HandleRequiredMiddleware:
    """Send staff who have not picked a work address to pick one first."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method == "GET"
            and request.path.startswith(GATED_PREFIXES)
            and needs_handle(request.user)
        ):
            target = reverse("staff:choose-handle")
            return redirect(f"{target}?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)
