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

        # The address was free when the invitation was issued, but /signup/ is
        # public and creates users with username=email, so it may have been
        # taken since. Roll the claim back rather than burning the invitation
        # on a request that cannot succeed.
        if _email_is_taken(invitation.email):
            transaction.set_rollback(True)
            return HttpResponse(TAKEN, status=409)

        try:
            user = User.objects.create_user(
                username=invitation.email, email=invitation.email, is_staff=True
            )
        except IntegrityError:
            # Lost the race against a signup between the check above and here.
            transaction.set_rollback(True)
            return HttpResponse(TAKEN, status=409)

        user.set_password(password1)
        user.save()
        user.groups.set(invitation.groups.all())

        record(
            actor=None,
            action="invite_accepted",
            summary=f"{invitation.email} accepted their invitation",
            target_user=user,
            detail={"roles": sorted(g.name for g in user.groups.all())},
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
