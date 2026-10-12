from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from .handles import needs_handle
from .models import StaffProfile

# The HTML pages of the panel. APIs are left alone: a page that never
# loads cannot call them, and a 302 would only confuse fetch().
GATED_PREFIXES = ("/admin-panel/", "/appointments/", "/editorial/")


def needs_onboarding(user):
    """True for a staff account that has not completed onboarding.

    A staff account with no StaffProfile row has not onboarded either. Rows
    only exist for people who accepted an invitation after onboarding
    shipped, so treating "no row" as "nothing to do" let every older account,
    and every account made through createsuperuser or /admin/, skip it. The
    onboarding view creates the row on first visit.
    """
    # is_superuser as well as is_staff: the panel lets a superuser in on
    # either flag (brand.views.is_admin), so the gate must not skip one.
    if not (user.is_authenticated and (user.is_staff or user.is_superuser)):
        return False
    if needs_handle(user):
        return False
    profile = getattr(user, "staff_profile", None)
    return profile is None or not profile.is_onboarded


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
