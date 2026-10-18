from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from messaging.mailbox import claim_unmatched

from .audit import record
from .handles import mailbox_address, needs_handle, suggest_handles, validate_handle
from .models import StaffInvitation
from .signups import TAKEN as ACCOUNT_TAKEN, account_for
from .profile_options import (
    COMMON_FRAMEWORKS,
    COMMON_LANGUAGES,
    ROLE_CHOICES,
    SCOPE_CHOICES,
    clean_list,
)
from .tokens import read_invitation_token

GONE = "This invitation link is no longer valid. Ask an administrator for a new one."
TAKEN = (
    "An account already exists for this address. Ask an administrator to grant "
    "your existing account access instead."
)


def _email_is_taken(email):
    return User.objects.filter(
        Q(username__iexact=email) | Q(email__iexact=email)
    ).exists()


def accept_invitation(request, token):
    try:
        invitation_id = read_invitation_token(token)
    except (signing.BadSignature, signing.SignatureExpired):
        return HttpResponse(GONE, status=410)

    invitation = StaffInvitation.objects.filter(
        pk=invitation_id, accepted_at__isnull=True
    ).first()
    if invitation is None:
        return HttpResponse(GONE, status=410)

    if request.method != "POST":
        return render(
            request, "staff/accept_invitation.html", {"invitation": invitation}
        )

    password1 = request.POST.get("password1") or ""
    password2 = request.POST.get("password2") or ""
    error = None
    if password1 != password2:
        error = "The two passwords do not match."
    else:
        # Run the project's configured validators rather than a bare length
        # check: this is the only form in the codebase that mints is_staff
        # accounts, so it should not be the one place a common or
        # all-numeric password gets through. The unsaved User gives
        # UserAttributeSimilarityValidator something to compare against.
        try:
            validate_password(
                password1,
                user=User(username=invitation.email, email=invitation.email),
            )
        except ValidationError as exc:
            error = " ".join(exc.messages)

    if error:
        return render(
            request,
            "staff/accept_invitation.html",
            {"invitation": invitation, "error": error},
        )

    with transaction.atomic():
        # Claim the invitation before creating anything. If a second request
        # got here first this updates zero rows and we stop, so one link can
        # never mint two accounts. Same guarded-update pattern the outbox uses.
        claimed = StaffInvitation.objects.filter(
            pk=invitation.pk, accepted_at__isnull=True
        ).update(accepted_at=timezone.now())
        if not claimed:
            return HttpResponse(GONE, status=410)

        # A staff account may have taken the address since the invitation was
        # issued. Roll the claim back rather than burning the invitation on a
        # request that cannot succeed. A /signup/ account is taken over
        # instead: reaching this point proves the person holds the inbox,
        # which the sign-up never did (see staff/signups.py).
        existing = account_for(invitation.email)
        if existing is ACCOUNT_TAKEN:
            transaction.set_rollback(True)
            return HttpResponse(TAKEN, status=409)

        if existing is None:
            try:
                user = User.objects.create_user(
                    username=invitation.email, email=invitation.email, is_staff=True
                )
            except IntegrityError:
                # Lost the race against a signup between the check above and here.
                transaction.set_rollback(True)
                return HttpResponse(TAKEN, status=409)
        else:
            user = User.objects.select_for_update().get(pk=existing.pk)
            user.is_staff = True
            # /signup/ creates accounts deactivated; accepting switches them on.
            user.is_active = True
            user.email = invitation.email

        # On a taken-over sign-up the new password also changes the session
        # auth hash, so anyone already signed in to it is signed out.
        user.set_password(password1)
        user.save()
        user.groups.set(invitation.groups.all())

        from .models import StaffProfile
        StaffProfile.objects.get_or_create(user=user, defaults={"is_onboarded": False})

        record(
            actor=None,
            action="invite_accepted",
            summary=f"{invitation.email} accepted their invitation",
            target_user=user,
            detail={
                "roles": sorted(g.name for g in user.groups.all()),
                "took_over_signup": existing is not None,
            },
        )

    return redirect("login")


@login_required
def choose_handle(request):
    """Pick a work address once. It becomes the username and the mailbox."""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = ""
    next_url = next_url or "/admin-panel/"

    if not needs_handle(request.user):
        return redirect(next_url)

    context = {
        "next": next_url,
        "mailbox_domain": settings.MAILBOX_DOMAIN,
        "suggestions": suggest_handles(request.user),
        "value": request.POST.get("handle", ""),
    }
    if request.method != "POST":
        return render(request, "staff/choose_handle.html", context)

    user = request.user
    previous = user.username
    try:
        with transaction.atomic():
            handle = validate_handle(request.POST.get("handle"), user=user)
            # Guarded like the invitation claim: a double submit updates
            # nothing the second time, so a handle is only ever picked once.
            changed = User.objects.filter(pk=user.pk, username=previous).update(
                username=handle
            )
            if changed:
                user.username = handle
                claim_unmatched(user)
                record(
                    actor=user,
                    action="handle_chosen",
                    summary=f"{user.email} chose {mailbox_address(handle)}",
                    target_user=user,
                    detail={"handle": handle, "previous_username": previous},
                )
    except ValidationError as exc:
        context["error"] = " ".join(exc.messages)
        return render(request, "staff/choose_handle.html", context)
    except IntegrityError:
        context["error"] = "Someone just took that address. Pick another."
        return render(request, "staff/choose_handle.html", context)

    return redirect(next_url)


@login_required
def onboarding(request):
    """Guided onboarding: WhatsApp, the area of the business they work in, and skills."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect("/")

    if needs_handle(request.user):
        return redirect("staff:choose-handle")

    from .models import StaffProfile
    from .phone import normalize_phone

    profile, _ = StaffProfile.objects.get_or_create(user=request.user)

    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = ""
    next_url = next_url or "/admin-panel/"

    context = {
        "next": next_url,
        "profile": profile,
        "role_choices": ROLE_CHOICES,
        "scope_choices": SCOPE_CHOICES,
        "common_languages": COMMON_LANGUAGES,
        "common_frameworks": COMMON_FRAMEWORKS,
        "user_scopes": profile.scopes or [],
        "user_languages": profile.coding_languages or [],
        "user_frameworks": profile.frameworks or [],
        "phone_value": profile.phone or "",
        "github_value": profile.github_username or "",
        "bio_value": profile.bio or "",
        "primary_role_value": profile.primary_role or "",
    }

    if request.method != "POST":
        return render(request, "staff/onboarding.html", context)

    raw_phone = request.POST.get("phone", "").strip()
    primary_role = request.POST.get("primary_role", "").strip()
    github_username = request.POST.get("github_username", "").strip()
    bio = request.POST.get("bio", "").strip()

    def picked(field, custom_field):
        extra = request.POST.get(custom_field, "").split(",")
        return clean_list(request.POST.getlist(field) + extra)

    scopes = picked("scopes", "custom_scopes")
    coding_languages = picked("coding_languages", "custom_languages")
    frameworks = picked("frameworks", "custom_frameworks")

    def redisplay(error):
        # Hand back what they typed, so a mistake costs one field not the form.
        context.update(
            error=error,
            phone_value=raw_phone,
            primary_role_value=primary_role,
            github_value=github_username,
            bio_value=bio,
            user_scopes=scopes,
            user_languages=coding_languages,
            user_frameworks=frameworks,
        )
        return render(request, "staff/onboarding.html", context)

    if not raw_phone:
        return redisplay("A WhatsApp phone number is required so the team can reach you.")

    try:
        phone = normalize_phone(raw_phone)
    except ValidationError as exc:
        return redisplay(" ".join(exc.messages))

    if not scopes:
        return redisplay(
            "Pick at least one area you work in, so the team knows where to find you."
        )

    profile.phone = phone
    profile.primary_role = primary_role
    profile.scopes = scopes
    profile.coding_languages = coding_languages
    profile.frameworks = frameworks
    profile.github_username = github_username
    profile.bio = bio
    profile.is_onboarded = True
    profile.save()

    record(
        actor=request.user,
        action="onboarding_completed",
        summary=f"{request.user.username} completed onboarding",
        target_user=request.user,
        detail={
            "phone": phone,
            "primary_role": primary_role,
            "scopes": scopes,
            "coding_languages": coding_languages,
            "frameworks": frameworks,
            "github_username": github_username,
        },
    )

    return redirect(next_url)
