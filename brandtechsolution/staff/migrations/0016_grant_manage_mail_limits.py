from django.db import migrations

CODENAME = "manage_mail_limits"
LABEL = "Set mail sending limits"


def grant_to_administrator(apps, schema_editor):
    """Give the Administrator preset the new capability, as 0010 and 0014
    did. Setting how much everyone may send is an administrator's call.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="staff", model="staffcapability"
    )
    permission, _ = Permission.objects.get_or_create(
        codename=CODENAME, content_type=content_type, defaults={"name": LABEL}
    )

    group = Group.objects.filter(name="Administrator").first()
    if group is not None:
        group.permissions.add(permission)


def revoke_from_administrator(apps, schema_editor):
    """Undo only the grant this migration made.

    Deleting the permission row outright would cascade to every group and user
    granted it by hand, so a rollback would quietly discard an administrator's
    own configuration.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    permission = Permission.objects.filter(
        codename=CODENAME, content_type__app_label="staff"
    ).first()
    if permission is None:
        return

    group = Group.objects.filter(name="Administrator").first()
    if group is not None:
        group.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0015_mail_limits"),
        ("auth", "__first__"),
        ("contenttypes", "__first__"),
    ]

    operations = [
        migrations.RunPython(grant_to_administrator, revoke_from_administrator),
    ]
