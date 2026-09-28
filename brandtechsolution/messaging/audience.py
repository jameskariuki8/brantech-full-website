from django.contrib.auth.models import User

from django.conf import settings
from django.db.models import Q

from appointments.models import Appointment
from .models import BlockedSender, CampaignExclusion, CampaignRecipient, Contact, Inquiry, Suppression
from .validation import validate_syntax

SOURCE_KEYS = {"inquiries", "users", "appointments"}


def _iter_source(key):
    """Yield (email, name) pairs for a source key."""
    if key == "inquiries":
        for name, email in Inquiry.objects.values_list("name", "email"):
            yield email, name
    elif key == "users":
        # Customers only: staff hear about things through the panel.
        for first, last, email in User.objects.exclude(email="").filter(is_staff=False).values_list(
            "first_name", "last_name", "email"
        ):
            yield email, (f"{first} {last}".strip())
    elif key == "appointments":
        for name, email in Appointment.objects.values_list("full_name", "email"):
            yield email, name


def _iter_contacts(selection):
    """(email, name) for the contacts a campaign audience picks: everyone,
    or anyone in the chosen segments or from the chosen origins."""
    if not selection:
        return
    qs = Contact.objects.all()
    if not selection.get("everyone"):
        q = Q()
        if selection.get("segments"):
            q |= Q(segments__in=selection["segments"])
        if selection.get("origins"):
            q |= Q(source__in=selection["origins"])
        if not q:
            return
        qs = qs.filter(q).distinct()
    yield from qs.values_list("email", "name")


def resolve_recipients(source_keys, manual_emails, contacts=None):
    """Merge selected sources, contacts and a manual list into deduped,
    suppression-filtered dicts."""
    suppressed = {
        (e or "").strip().lower()
        for e in Suppression.objects.values_list("email", flat=True)
    }
    # Senders marked as spam in the mail client, and our own addresses.
    suppressed |= set(BlockedSender.objects.values_list("email", flat=True))
    own_domain = "@" + settings.MAILBOX_DOMAIN.lower()
    merged = {}  # email(lower) -> name

    for key in source_keys:
        if key not in SOURCE_KEYS:
            continue
        for email, name in _iter_source(key):
            if not email:
                continue
            e = email.strip().lower()
            merged.setdefault(e, (name or "").strip())

    for email, name in _iter_contacts(contacts):
        merged.setdefault(email.strip().lower(), (name or "").strip())

    for email in manual_emails or []:
        e = (email or "").strip().lower()
        if e:
            merged.setdefault(e, "")

    return [
        {"email": e, "name": n}
        for e, n in merged.items()
        if e not in suppressed and not e.endswith(own_domain)
    ]


def build_recipients(campaign, source_keys, manual_emails, contacts=None):
    """Materialize resolved recipients as CampaignRecipient rows; set campaign.total.

    Drops any address the admin has deliberately removed from this campaign
    before (see CampaignExclusion) -- otherwise a rebuild would silently
    resurrect it. `resolve_recipients` already normalises candidates via
    `.strip().lower()`, so the exclusion set is normalised the same way to
    match.
    """
    recipients = resolve_recipients(source_keys, manual_emails, contacts)
    excluded = {
        (e or "").strip().lower()
        for e in CampaignExclusion.objects.filter(campaign=campaign).values_list(
            "email", flat=True
        )
    }
    recipients = [r for r in recipients if r["email"] not in excluded]
    CampaignRecipient.objects.bulk_create(
        [
            CampaignRecipient(
                campaign=campaign,
                email=r["email"],
                name=r["name"],
                validation_status=(
                    "valid" if validate_syntax(r["email"]) else "invalid_syntax"
                ),
            )
            for r in recipients
        ],
        ignore_conflicts=True,
    )
    count = CampaignRecipient.objects.filter(campaign=campaign).count()
    campaign.total = count
    campaign.save(update_fields=["total"])
    return count
