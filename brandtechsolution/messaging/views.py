from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from brandtechsolution import turnstile
from .models import Inquiry, Suppression
from .tokens import read_unsubscribe_token


def _is_ajax(request):
    accept = request.headers.get("Accept", "")
    return (
        "application/json" in accept
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def _client_ip(request):
    """Best-effort client IP. The app runs behind a Cloudflare tunnel, so the
    real client address arrives as the first entry of X-Forwarded-For; fall
    back to REMOTE_ADDR for direct connections (e.g. local dev/tests)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _contact_rate_limited(request):
    """Increment and check the per-IP contact-form counter. Returns True if
    this request is over the limit (and must be dropped)."""
    ip = _client_ip(request)
    key = f"contact_rate:{ip}"
    count = cache.get(key)
    if count is None:
        cache.set(key, 1, timeout=settings.CONTACT_RATE_LIMIT_WINDOW_SECONDS)
        return False
    if count >= settings.CONTACT_RATE_LIMIT_COUNT:
        return True
    cache.set(key, count + 1, timeout=settings.CONTACT_RATE_LIMIT_WINDOW_SECONDS)
    return False


@require_POST
def contact_submit(request):
    """Public contact-form endpoint. Replaces the old Formspree POST target."""
    ajax = _is_ajax(request)

    if _contact_rate_limited(request):
        error = "Too many submissions. Please try again later."
        if ajax:
            return JsonResponse({"ok": False, "error": error}, status=429)
        messages.error(request, error)
        return redirect("contacts")

    # Turnstile sits alongside the honeypot and the rate limit rather than
    # replacing them: the honeypot costs a naive bot nothing to trip, the
    # rate limit bounds a determined one, and Turnstile handles the middle
    # ground that clears both. Checked after the rate limit so a flood cannot
    # make us call Cloudflare once per request.
    if not turnstile.passed(request):
        if ajax:
            return JsonResponse({"ok": False, "error": turnstile.FAILED}, status=400)
        messages.error(request, turnstile.FAILED)
        return redirect("contacts")

    # Honeypot: real users never fill the hidden 'website' field.
    if request.POST.get("website"):
        if ajax:
            return JsonResponse({"ok": True})
        messages.success(request, "Thanks! Your message has been sent.")
        return redirect("contacts")

    name = (request.POST.get("name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    message = (request.POST.get("message") or "").strip()

    if not (name and email and message):
        if ajax:
            return JsonResponse(
                {"ok": False, "error": "Please fill in your name, email, and message."},
                status=400,
            )
        messages.error(request, "Please fill in your name, email, and message.")
        return redirect("contacts")

    inquiry = Inquiry.objects.create(
        name=name, email=email, phone=phone, message=message
    )

    try:
        send_mail(
            subject=f"New Contact Inquiry from {name}",
            message=(
                f"New Contact Form Submission on Teklora:\n\n"
                f"Full Name: {name}\n"
                f"Email Address: {email}\n"
                f"Phone / WhatsApp: {phone or 'N/A'}\n\n"
                f"Inquiry Message:\n{message}\n"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "juniorkariuki735@gmail.com") or "juniorkariuki735@gmail.com",
            recipient_list=[
                "juniorkariuki735@gmail.com",
                "mugishalionel02@gmail.com",
                "teklorasolutionsltd@gamil.com",
                "leonmusungu138@gmail.com",
                "davidnjihia536@gmail.com",
            ],
            fail_silently=True,
        )
    except Exception:
        # Notification is best-effort; the inquiry is already saved.
        pass

    if ajax:
        return JsonResponse({"ok": True})
    messages.success(request, "Thanks! Your message has been sent.")
    return redirect("contacts")


# Exempt from CSRF: RFC 8058 one-click unsubscribe requires mail clients
# (Gmail, Outlook, etc.) to be able to POST the List-Unsubscribe-Post URL
# directly, with no CSRF token available. This is safe because the signed,
# per-recipient token in the URL is itself the authorization credential
# (unguessable, tied to one email address), and the action it gates
# (suppressing that address) is idempotent and purely self-service -- it
# cannot be leveraged against any other account or data.
@csrf_exempt
def unsubscribe(request, token):
    try:
        email = read_unsubscribe_token(token)
    except signing.BadSignature:
        return HttpResponse("Invalid or expired unsubscribe link.", status=400)

    if request.method == "POST":
        Suppression.objects.get_or_create(
            email=email, defaults={"reason": "unsubscribed"}
        )
        return HttpResponse(
            "<h1>You've been unsubscribed</h1>"
            "<p>You will no longer receive bulk emails from us.</p>",
            status=200,
        )

    # GET (and any other method): show a confirmation page only. No DB write --
    # scanners and link-prefetchers (Gmail, Outlook, corporate filters) fetch
    # links in message bodies, and a bare GET must never unsubscribe someone
    # who never clicked anything.
    return render(request, "messaging/unsubscribe_confirm.html", {"email": email})
