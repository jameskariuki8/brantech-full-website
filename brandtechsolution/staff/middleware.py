from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from .handles import needs_handle
from .models import StaffProfile

# The HTML pages of the panel. APIs are left alone: a page that never
# loads cannot call them, and a 302 would only confuse fetch().
GATED_PREFIXES = ("/admin-panel/", "/appointments/", "/editorial/")


def needs_onboarding(user):
    """True for a staff account that has an uncompleted onboarding profile."""
    if not (user.is_authenticated and user.is_staff):
        return False
    if needs_handle(user):
        return False
    profile = getattr(user, "staff_profile", None)
    if profile is not None and not profile.is_onboarded:
        return True
    return False


class HandleRequiredMiddleware:
    """Send staff who have not picked a work address or completed onboarding to do so."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "GET" and request.path.startswith(GATED_PREFIXES):
            if needs_handle(request.user):
                target = reverse("staff:choose-handle")
                return redirect(f"{target}?{urlencode({'next': request.get_full_path()})}")
            if needs_onboarding(request.user):
                target = reverse("staff:onboarding")
                return redirect(f"{target}?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)
