from django.contrib.auth.models import User

from appointments.models import Appointment
from .models import CampaignRecipient, Inquiry, Suppression

SOURCE_KEYS = {"inquiries", "users", "appointments"}


def _iter_source(key):
    """Yield (email, name) pairs for a source key."""
    if key == "inquiries":
        for name, email in Inquiry.objects.values_list("name", "email"):
            yield email, name
    elif key == "users":
        for first, last, email in User.objects.exclude(email="").values_list(
            "first_name", "last_name", "email"
        ):
            yield email, (f"{first} {last}".strip())
    elif key == "appointments":
        for name, email in Appointment.objects.values_list("full_name", "email"):
            yield email, name


def resolve_recipients(source_keys, manual_emails):
    """Merge selected sources + manual list into deduped, suppression-filtered dicts."""
    suppressed = set(Suppression.objects.values_list("email", flat=True))
    merged = {}  # email(lower) -> name

    for key in source_keys:
        if key not in SOURCE_KEYS:
            continue
        for email, name in _iter_source(key):
            if not email:
                continue
            e = email.strip().lower()
            merged.setdefault(e, (name or "").strip())

    for email in manual_emails or []:
        e = (email or "").strip().lower()
        if e:
            merged.setdefault(e, "")

    return [
        {"email": e, "name": n}
        for e, n in merged.items()
        if e not in suppressed
    ]


def build_recipients(campaign, source_keys, manual_emails):
    """Materialize resolved recipients as CampaignRecipient rows; set campaign.total."""
    recipients = resolve_recipients(source_keys, manual_emails)
    CampaignRecipient.objects.bulk_create(
        [
            CampaignRecipient(campaign=campaign, email=r["email"], name=r["name"])
            for r in recipients
        ],
        ignore_conflicts=True,
    )
    count = CampaignRecipient.objects.filter(campaign=campaign).count()
    campaign.total = count
    campaign.save(update_fields=["total"])
    return count
