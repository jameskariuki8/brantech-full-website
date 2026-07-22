from django.conf import settings
from django.core import signing

INVITATION_SALT = "staff.invite"
DEFAULT_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def make_invitation_token(invitation_id: int) -> str:
    return signing.dumps({"id": invitation_id}, salt=INVITATION_SALT)


def read_invitation_token(token: str) -> int:
    """Return the invitation id.

    Raises signing.SignatureExpired if older than the configured max age, or
    signing.BadSignature if tampered with.
    """
    max_age = getattr(settings, "STAFF_INVITATION_MAX_AGE", DEFAULT_MAX_AGE)
    return signing.loads(token, salt=INVITATION_SALT, max_age=max_age)["id"]
