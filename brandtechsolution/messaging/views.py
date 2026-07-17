from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .models import Inquiry


def _is_ajax(request):
    accept = request.headers.get("Accept", "")
    return (
        "application/json" in accept
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


@require_POST
def contact_submit(request):
    """Public contact-form endpoint. Replaces the old Formspree POST target."""
    ajax = _is_ajax(request)

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
            subject=f"New contact inquiry from {name}",
            message=f"From: {name} <{email}>\nPhone: {phone or 'n/a'}\n\n{message}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.DEFAULT_FROM_EMAIL],
            fail_silently=True,
        )
    except Exception:
        # Notification is best-effort; the inquiry is already saved.
        pass

    if ajax:
        return JsonResponse({"ok": True})
    messages.success(request, "Thanks! Your message has been sent.")
    return redirect("contacts")
