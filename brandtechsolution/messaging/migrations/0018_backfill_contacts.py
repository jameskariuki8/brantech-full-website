"""Put everyone already on file into Contacts: inquiries, bookings and
customer accounts, oldest first so each keeps where it first came from.
From here on signals.py does this as they arrive."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import migrations


def backfill(apps, schema_editor):
    Contact = apps.get_model("messaging", "Contact")
    Inquiry = apps.get_model("messaging", "Inquiry")
    BlockedSender = apps.get_model("messaging", "BlockedSender")
    Appointment = apps.get_model("appointments", "Appointment")
    User = apps.get_model("auth", "User")

    own = "@" + settings.MAILBOX_DOMAIN.lower()
    blocked = set(BlockedSender.objects.values_list("email", flat=True))
    people = {}  # email -> details gathered from every sighting

    def see(email, name, phone, source, when):
        email = (email or "").strip().lower()
        if not email or email.endswith(own) or email in blocked:
            return
        try:
            validate_email(email)
        except ValidationError:
            return
        row = people.setdefault(email, {"name": "", "phone": "", "source": source, "when": when})
        if when and row["when"] and when < row["when"]:
            row["source"], row["when"] = source, when
        row["name"] = row["name"] or (name or "").strip()
        row["phone"] = row["phone"] or (phone or "").strip()

    for name, email, phone, when in Inquiry.objects.values_list("name", "email", "phone", "created_at"):
        see(email, name, phone, "inquiry", when)
    for name, email, phone, when in Appointment.objects.values_list("full_name", "email", "phone", "created_at"):
        see(email, name, phone, "appointment", when)
    for first, last, email, when in User.objects.filter(is_staff=False).exclude(email="").values_list(
        "first_name", "last_name", "email", "date_joined"
    ):
        see(email, f"{first} {last}".strip(), "", "account", when)

    Contact.objects.bulk_create(
        [
            Contact(email=e, name=r["name"][:200], phone=r["phone"][:40], source=r["source"])
            for e, r in people.items()
        ],
        ignore_conflicts=True,
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0017_contacts"),
        ("appointments", "0007_alter_appointment_email_alter_appointment_phone"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
