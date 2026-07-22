from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from .tokens import make_invitation_token


def send_invitation(invitation, request=None):
    """Send the invitation link.

    Sent directly rather than through the campaign outbox: an invitation is
    transactional and must not queue behind a bulk send.
    """
    path = reverse(
        "staff:accept-invitation",
        kwargs={"token": make_invitation_token(invitation.pk)},
    )
    url = request.build_absolute_uri(path) if request else path
    inviter = invitation.invited_by or "An administrator"

    send_mail(
        subject="You have been invited to the Teklora admin panel",
        message=(
            f"{inviter} has invited you to the Teklora admin panel.\n\n"
            f"Set your password to activate your account:\n{url}\n\n"
            "This link expires in 7 days. If you were not expecting this "
            "invitation you can ignore this message."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invitation.email],
        fail_silently=False,
    )
