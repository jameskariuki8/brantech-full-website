from django.db import migrations

# Names that became shared mailboxes (staff.handles.SHARED_MAILBOXES). Mail to
# them used to land in "other" because nothing owned the address.
NAMES = ["careers", "jobs", "hr", "sales", "billing", "contact"]


def refile(apps, schema_editor):
    """Move threads already sitting in Unmatched into the shared mailbox their
    address now belongs to. Matched on the address a message was delivered to,
    exactly as claiming a personal handle does."""
    from django.conf import settings

    MailThread = apps.get_model("messaging", "MailThread")
    MailMessage = apps.get_model("messaging", "MailMessage")
    domain = settings.MAILBOX_DOMAIN.lower()
    for name in NAMES:
        thread_ids = MailMessage.objects.filter(
            thread__owner__isnull=True,
            thread__mailbox="other",
            delivered_to__iexact=f"{name}@{domain}",
        ).values_list("thread_id", flat=True)
        MailThread.objects.filter(pk__in=list(thread_ids)).update(mailbox=name)


class Migration(migrations.Migration):

    dependencies = [("messaging", "0019_mail_attachments")]

    operations = [migrations.RunPython(refile, migrations.RunPython.noop)]
