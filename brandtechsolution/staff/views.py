from django.contrib.auth.models import User
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .audit import record
from .models import StaffInvitation
from .tokens import read_invitation_token

GONE = "This invitation link is no longer valid. Ask an administrator for a new one."


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
    elif len(password1) < 10:
        error = "Choose a password of at least 10 characters."

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

        user = User.objects.create_user(
            username=invitation.email, email=invitation.email, is_staff=True
        )
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

    return redirect("/login/")
