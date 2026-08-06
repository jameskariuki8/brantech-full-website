import email.utils
import hashlib
import hmac
import json
import logging
import time
import urllib.parse

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
from staff.emails import capability_holder_emails
from .models import InboundEmail, Inquiry, Suppression
from .tokens import read_unsubscribe_token

logger = logging.getLogger(__name__)




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

    # Whoever currently holds handle_inquiries, rather than a list of addresses
    # compiled into this module. Someone leaving the team stops receiving
    # customer contact details the moment their capability is revoked.
    recipients = capability_holder_emails("handle_inquiries")
    if not recipients:
        logger.warning(
            "No handle_inquiries holder has an email address; inquiry #%s "
            "saved with nobody notified.",
            inquiry.pk,
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
            # A gmail.com From address cannot pass SPF/DKIM alignment for mail
            # Mailgun sends, so it is no longer an acceptable fallback.
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        # Notification is best-effort; the inquiry is already saved and shows
        # in the panel's inbox regardless.
        logger.exception("Could not send contact notification for %s", email)

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


def _parse_mailgun_payload(request):
    """Parses incoming payload safely from form data or JSON body based on content_type."""
    data = {}
    content_type = (getattr(request, "content_type", "") or "").lower()
    if "application/json" in content_type:
        try:
            body_json = json.loads(request.body.decode("utf-8"))
            if isinstance(body_json, dict):
                data.update(body_json)
        except Exception:
            pass
    else:
        if request.POST:
            data.update(request.POST.dict())
        elif request.body:
            try:
                parsed = urllib.parse.parse_qs(request.body.decode("utf-8"))
                for k, v in parsed.items():
                    data[k] = v[-1] if isinstance(v, list) and v else v
            except Exception:
                pass
    return data


def _verify_mailgun_signature(request, payload=None):
    """
    Verifies Mailgun's HTTP webhook signature using HMAC-SHA256.
    Supports standard signatures, subaccount parent-signatures, timestamp freshness,
    and replay attack prevention via token caching.
    """
    if getattr(settings, "MAILGUN_SKIP_WEBHOOK_VERIFICATION", False) or getattr(settings, "TESTING", False):
        logger.warning("Mailgun signature verification bypassed via settings/TESTING mode.")
        return True

    if payload is None:
        payload = _parse_mailgun_payload(request)

    # Extract signature elements (from flat payload or nested signature dict)
    sig_dict = payload.get("signature") if isinstance(payload.get("signature"), dict) else {}
    timestamp_raw = str(sig_dict.get("timestamp") or payload.get("timestamp") or payload.get("signature[timestamp]") or "")
    token = str(sig_dict.get("token") or payload.get("token") or payload.get("signature[token]") or "")
    signature = str(sig_dict.get("signature") or payload.get("signature") or payload.get("signature[signature]") or "")
    parent_signature = str(
        sig_dict.get("parent-signature")
        or payload.get("parent-signature")
        or payload.get("signature[parent-signature]")
        or ""
    )

    api_key = getattr(settings, "MAILGUN_API_KEY", "").strip()
    signing_key = getattr(settings, "MAILGUN_WEBHOOK_SIGNING_KEY", "").strip()

    candidate_keys = [k for k in [signing_key, api_key] if k]

    logger.debug(
        "Mailgun sig check — timestamp=%r token=%r signature=%r parent_signature=%r "
        "signing_key_set=%s api_key_set=%s payload_keys=%s",
        timestamp_raw, token, signature, parent_signature,
        bool(signing_key), bool(api_key), sorted(payload.keys()),
    )

    if not candidate_keys:
        logger.warning(
            "Mailgun webhook rejected: no signing key configured "
            "(set MAILGUN_WEBHOOK_SIGNING_KEY in your environment)."
        )
        # Fail open only in DEBUG so misconfiguration doesn't lock out production.
        return bool(settings.DEBUG)

    if not timestamp_raw or not token or not signature:
        logger.warning(
            "Mailgun webhook rejected: missing signature fields — "
            "timestamp=%r token=%r signature=%r",
            timestamp_raw, token, signature,
        )
        return False

    # Timestamp freshness check (allow up to 15 minutes drift by default)
    try:
        ts = int(timestamp_raw)
        max_drift = getattr(settings, "MAILGUN_WEBHOOK_MAX_AGE", 900)
        drift = abs(time.time() - ts)
        if max_drift > 0 and drift > max_drift:
            logger.warning(
                "Mailgun webhook rejected: timestamp too old/future — drift=%.0fs limit=%ss timestamp=%s",
                drift, max_drift, timestamp_raw,
            )
            return False
    except (ValueError, TypeError):
        logger.warning("Mailgun webhook rejected: invalid timestamp format — %r", timestamp_raw)
        return False

    message = f"{timestamp_raw}{token}".encode("utf-8")
    valid = False
    for key in candidate_keys:
        computed_sig = hmac.new(
            key=key.encode("utf-8"),
            msg=message,
            digestmod=hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(computed_sig, signature) or (
            parent_signature and hmac.compare_digest(computed_sig, parent_signature)
        ):
            valid = True
            break

    if not valid:
        logger.warning(
            "Mailgun webhook rejected: HMAC mismatch — "
            "computed does not match provided signature. "
            "Verify MAILGUN_WEBHOOK_SIGNING_KEY matches the Webhook Signing Key "
            "in your Mailgun dashboard (not the API key)."
        )
        return False

    # Replay attack prevention: cache token for 24 hours
    cache_key = f"mailgun_webhook_token:{token}"
    if not cache.add(cache_key, "1", timeout=86400):
        logger.warning("Mailgun webhook rejected: replay attack — token %s already processed.", token)
        return False

    return True


@csrf_exempt
@require_POST
def mailgun_inbound_webhook(request):
    """
    Webhook endpoint to receive inbound emails routed from Mailgun.
    Creates both an InboundEmail record and an Inquiry record for administrative visibility,
    and alerts team members holding the 'handle_inquiries' capability.
    """
    payload = _parse_mailgun_payload(request)

    if not _verify_mailgun_signature(request, payload=payload):
        logger.warning("Invalid signature on Mailgun inbound webhook request.")
        return JsonResponse({"ok": False, "error": "Invalid signature"}, status=406)

    raw_sender = str(payload.get("sender") or payload.get("from") or payload.get("From") or "")
    raw_recipient = str(payload.get("recipient") or payload.get("to") or payload.get("To") or "")
    sender_name, sender_email = email.utils.parseaddr(raw_sender)
    if not sender_email:
        sender_email = raw_sender

    subject = str(payload.get("subject") or "").strip()
    body_plain = str(
        payload.get("stripped-text")
        or payload.get("body-plain")
        or payload.get("text")
        or ""
    ).strip()
    body_html = str(
        payload.get("stripped-html")
        or payload.get("body-html")
        or payload.get("html")
        or ""
    ).strip()

    # Save raw inbound email record
    inbound_email = InboundEmail.objects.create(
        sender=sender_email,
        recipient=raw_recipient,
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
        message_headers={"raw_sender": raw_sender, "raw_recipient": raw_recipient},
    )

    # Automatically create Inquiry for admin dashboard visibility
    display_name = sender_name or sender_email
    inquiry_message = f"[Inbound Mailgun Email to {raw_recipient}]\nSubject: {subject}\n\n{body_plain}"

    inquiry = Inquiry.objects.create(
        name=display_name,
        email=sender_email,
        phone="",
        message=inquiry_message,
    )

    # Broadcast notification to team members holding 'handle_inquiries' capability
    recipients = capability_holder_emails("handle_inquiries")
    if recipients:
        try:
            send_mail(
                subject=f"[Inbound Email] {subject or 'New Customer Message'} from {display_name}",
                message=(
                    f"New Inbound Email Received via Mailgun:\n\n"
                    f"From: {display_name} <{sender_email}>\n"
                    f"To: {raw_recipient}\n"
                    f"Subject: {subject}\n\n"
                    f"Message Body:\n{body_plain}\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=True,
            )
        except Exception:
            logger.exception("Failed to notify team of inbound Mailgun email from %s", sender_email)

    return JsonResponse({
        "ok": True,
        "inbound_id": inbound_email.pk,
        "inquiry_id": inquiry.pk,
    })


