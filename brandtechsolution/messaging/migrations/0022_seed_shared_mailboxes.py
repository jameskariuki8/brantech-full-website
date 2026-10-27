from django.db import migrations

# The list that was hardcoded as staff.handles.SHARED_MAILBOXES. Seeded with
# no groups, so access is exactly what it was: view_inbox reads them all.
NAMES = ["info", "hello", "support", "careers", "jobs", "hr", "sales", "billing", "contact"]


def seed(apps, schema_editor):
    SharedMailbox = apps.get_model("messaging", "SharedMailbox")
    for name in NAMES:
        SharedMailbox.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [("messaging", "0021_shared_mailbox")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
