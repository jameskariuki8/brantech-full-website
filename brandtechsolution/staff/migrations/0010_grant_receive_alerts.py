from django.db import migrations

CODENAME = "receive_alerts"
LABEL = "Receive system health alerts"


def grant_to_administrator(apps, schema_editor):
    """Give the Administrator preset the new capability.

    Same shape and same reasoning as 0007. 0002 defined Administrator as the
    role holding every capability, so a new one belongs in it -- and without
    this an agent could fail with nobody holding the capability to be told,
    which is the one outcome the alerting exists to prevent.

    Only Administrator is touched. Editor, Marketing and Support are scoped
    roles and being paged about a dead pipeline is not part of any of them, so
    they are left for an administrator to extend deliberately.

    The permission row is normally created by post_migrate, which has not run
    when this executes, so it is created here if absent. get_or_create keeps
    that idempotent when post_migrate later reaches the same row.
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
        ("staff", "0009_alter_staffcapability_options"),
        ("auth", "__first__"),
        ("contenttypes", "__first__"),
    ]

    operations = [
        migrations.RunPython(grant_to_administrator, revoke_from_administrator),
    ]
