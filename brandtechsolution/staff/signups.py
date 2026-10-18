"""Accounts made through the public /signup/ form.

/signup/ never checks that the address belongs to whoever typed it, so a
sign-up account must not be made staff directly: anyone could register a new
hire's address first and be handed their access. Instead it is invited like
anyone else, and accepting the emailed link - proof the person holds that
inbox - takes the account over: a new password, which also signs out every
session the sign-up had, then staff status and the invited roles.
"""

from django.contrib.auth.models import User
from django.db.models import Q

TAKEN = object()


def account_for(email):
    """What an invitation to `email` would land on.

    None when no account uses the address, the one sign-up account when that
    is all there is, and TAKEN when a staff account (or more than one account)
    already holds it.
    """
    matches = list(
        User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email))[:2]
    )
    if not matches:
        return None
    if len(matches) == 1 and not (matches[0].is_staff or matches[0].is_superuser):
        return matches[0]
    return TAKEN
