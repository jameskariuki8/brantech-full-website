from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .tokens import make_invitation_token


def capability_holder_emails(codename):
    """Email addresses of every staff account holding `codename`.

    Lets a notification address the people who can actually act on it rather
    than a hardcoded inbox, so granting or revoking a capability in the panel
    changes who gets told, with no configuration to keep in step.

    The three branches mirror what User.has_perm() consults -- a superuser
    holds everything implicitly, and a capability can be granted directly or
    through a role group. is_staff and is_active match the decorators in
    staff.decorators, which refuse a user failing either.
    """
    holders = (
        User.objects.filter(is_staff=True, is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(
                user_permissions__codename=codename,
                user_permissions__content_type__app_label="staff",
            )
            | Q(
                groups__permissions__codename=codename,
                groups__permissions__content_type__app_label="staff",
            )
        )
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
    )
    # distinct() on the queryset still leaves duplicates when one account holds
    # the capability both directly and via a group -- the join produces a row
    # for each. Deduplicate on the value, and sort so the recipient list is
    # stable rather than dependent on join order.
    return sorted(set(holders))


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

    # Stamped only after a successful send, so a failure leaves the invitation
    # looking unsent and the next attempt reissues it.
    invitation.last_sent_at = timezone.now()
    invitation.save(update_fields=["last_sent_at"])
