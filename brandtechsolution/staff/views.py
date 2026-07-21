from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .audit import record
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
