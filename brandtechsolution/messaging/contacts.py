"""Contacts: everyone outside the company we may email, grouped into
segments. Campaign audiences are built from here.

Addresses arrive on their own from inquiries, bookings and customer
accounts (signals.py), and from staff adding or importing them. Nothing
here decides whether someone may be emailed; Suppression does.
"""

import csv
import io
import logging
import os

from django.conf import settings
from django.db import IntegrityError, transaction

from .imports import EMAIL_RE, extract_emails_from_file
from .models import BlockedSender, Contact, Segment, Suppression
from .validation import validate_syntax

logger = logging.getLogger(__name__)

SOURCE_LABELS = dict(Contact.SOURCE_CHOICES)

# The same origins named as groups of people, for lists and audiences.
ORIGIN_GROUPS = [
    ("inquiry", "Website inquiries"),
    ("appointment", "Bookings"),
    ("account", "Customer accounts"),
    ("import", "Imported"),
    ("manual", "Added by hand"),
]

STATUS_LABELS = {
    "": "Subscribed",
    "unsubscribed": "Unsubscribed",
    "bounced": "Bounced",
    "complained": "Marked as spam",
    "manual": "Stopped by staff",
}


def normalise(email):
    return (email or "").strip().lower()


def is_ours(email):
    return email.endswith("@" + settings.MAILBOX_DOMAIN.lower())


def keepable(email, blocked=None):
    """Whether an address belongs in contacts at all: well formed, not one
    of our own mailboxes, and not a sender marked as spam."""
    if not email or not validate_syntax(email) or is_ours(email):
        return False
    if blocked is not None:
        return email not in blocked
    return not BlockedSender.objects.filter(email=email).exists()


def remember(email, name="", phone="", source="manual"):
    """Record an address seen somewhere on the site.

    Creates the contact the first time. After that it only fills fields
    that are still blank, so what staff typed in the panel is never
    overwritten by a later form submission. Returns the contact, or None
    for an address that is not kept.
    """
    email = normalise(email)
    if not keepable(email):
        return None
    name = (name or "").strip()[:200]
    phone = (phone or "").strip()[:40]
    try:
        with transaction.atomic():
            contact, created = Contact.objects.get_or_create(
                email=email, defaults={"name": name, "phone": phone, "source": source},
            )
    except IntegrityError:  # created by a concurrent request
        contact, created = Contact.objects.get(email=email), False
    if not created:
        changed = []
        if name and not contact.name:
            contact.name = name
            changed.append("name")
        if phone and not contact.phone:
            contact.phone = phone
            changed.append("phone")
        if changed:
            contact.save(update_fields=changed + ["updated_at"])
    return contact


def suppressed_emails():
    return Suppression.objects.values("email")


def reachable():
    """Contacts a campaign would actually send to."""
    return Contact.objects.exclude(email__in=suppressed_emails()).exclude(
        email__in=BlockedSender.objects.values("email")
    )


def statuses(emails):
    """email -> suppression reason, for the addresses given that have one."""
    return dict(
        Suppression.objects.filter(email__in=list(emails)).values_list("email", "reason")
    )


# --- importing ----------------------------------------------------------

HEADER_ALIASES = {
    "email": {"email", "e-mail", "email address", "e-mail address", "mail"},
    "name": {"name", "full name", "full_name", "contact", "contact name"},
    "first": {"first name", "first_name", "firstname", "given name"},
    "last": {"last name", "last_name", "lastname", "surname", "family name"},
    "phone": {"phone", "phone number", "mobile", "telephone", "tel", "whatsapp"},
    "company": {"company", "organisation", "organization", "business", "org"},
}


def _rows_from_csv(text):
    """Rows from a CSV whose header names an email column, or None when it
    has no such header (then any addresses in it are taken without names)."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except (StopIteration, csv.Error):
        return None
    cols = {}
    for i, heading in enumerate(header):
        key = heading.strip().lower()
        for field, names in HEADER_ALIASES.items():
            if key in names:
                cols.setdefault(field, i)
    if "email" not in cols:
        return None

    def cell(row, field):
        i = cols.get(field)
        return row[i].strip() if i is not None and i < len(row) else ""

    rows = []
    try:
        for row in reader:
            name = cell(row, "name") or f"{cell(row, 'first')} {cell(row, 'last')}".strip()
            rows.append((cell(row, "email"), name, cell(row, "phone"), cell(row, "company")))
    except csv.Error:
        pass
    return rows


def rows_from_text(text):
    return [(e, "", "", "") for e in EMAIL_RE.findall(text or "")]


def rows_from_file(upload):
    """(email, name, phone, company) for each person in an uploaded file.

    A CSV with an email column also gives names, phones and companies;
    any other file, or a CSV without headings, gives addresses only.
    Raises imports.UnsupportedFileType for other formats.
    """
    if os.path.splitext(upload.name)[1].lower() == ".csv":
        text = upload.read().decode("utf-8-sig", errors="ignore")
        rows = _rows_from_csv(text)
        return rows if rows is not None else rows_from_text(text)
    return [(e, "", "", "") for e in extract_emails_from_file(upload)]


def import_contacts(rows, segments=()):
    """Add people from an import and put all of them in `segments`.

    New addresses become contacts. Existing contacts keep what they have
    and only gain values for blank fields. Returns counts for the panel.
    """
    blocked = set(BlockedSender.objects.values_list("email", flat=True))
    wanted = {}  # email -> (name, phone, company); first row wins
    skipped = 0
    for email, name, phone, company in rows:
        email = normalise(email)
        if email in wanted:
            continue
        if not keepable(email, blocked):
            skipped += 1
            continue
        wanted[email] = ((name or "").strip()[:200], (phone or "").strip()[:40], (company or "").strip()[:200])

    with transaction.atomic():
        existing = {c.email: c for c in Contact.objects.filter(email__in=list(wanted))}
        Contact.objects.bulk_create(
            [
                Contact(email=e, name=n, phone=p, company=co, source="import")
                for e, (n, p, co) in wanted.items() if e not in existing
            ],
            ignore_conflicts=True,
        )
        for email, contact in existing.items():
            changed = []
            for field, value in zip(("name", "phone", "company"), wanted[email]):
                if value and not getattr(contact, field):
                    setattr(contact, field, value)
                    changed.append(field)
            if changed:
                contact.save(update_fields=changed + ["updated_at"])
        ids = list(Contact.objects.filter(email__in=list(wanted)).values_list("id", flat=True))
        for segment in segments:
            segment.contacts.add(*ids)

    return {
        "created": len(wanted) - len(existing),
        "existing": len(existing),
        "skipped": skipped,
    }


def segment_from_request(data):
    """The segments an import should go into: ids chosen, plus a new one
    named in `new_segment`. Returns (segments, error)."""
    ids = data.getlist("segments") if hasattr(data, "getlist") else data.get("segments") or []
    try:
        ids = [int(i) for i in ids if str(i).strip()]
    except (TypeError, ValueError):
        return [], "Segments must be ids."
    segments = list(Segment.objects.filter(pk__in=ids))
    new_name = (data.get("new_segment") or "").strip()[:80]
    if new_name:
        segment, _ = Segment.objects.get_or_create(
            name__iexact=new_name, defaults={"name": new_name}
        )
        segments.append(segment)
    return segments, None
