from django.core import signing

_SALT = "messaging.unsubscribe"


def make_unsubscribe_token(email: str) -> str:
    return signing.dumps(email.strip().lower(), salt=_SALT)


def read_unsubscribe_token(token: str) -> str:
    """Return the email encoded in the token. Raises signing.BadSignature if invalid."""
    return signing.loads(token, salt=_SALT)
