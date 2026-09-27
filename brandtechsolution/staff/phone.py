import re

from django.core.exceptions import ValidationError

# Most of the team is in Kenya, so a local number (0712 345 678) is read as
# +254. Anything else must already carry its country code.
DEFAULT_COUNTRY_CODE = "254"

_SEPARATORS = re.compile(r"[\s\-().]")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw):
    """Return `raw` as E.164, or "" for blank input. Raises ValidationError."""
    value = _SEPARATORS.sub("", raw or "")
    if not value:
        return ""
    if value.startswith("00"):
        value = "+" + value[2:]
    elif value.startswith("0"):
        value = f"+{DEFAULT_COUNTRY_CODE}{value[1:]}"
    elif not value.startswith("+"):
        value = "+" + value
    if not _E164.match(value):
        raise ValidationError(
            "Enter a phone number with its country code, e.g. +254712345678."
        )
    return value
