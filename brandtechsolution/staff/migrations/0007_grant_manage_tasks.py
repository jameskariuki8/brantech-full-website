from django.db import migrations

CODENAME = "manage_tasks"
LABEL = "Assign and review tasks"


def grant_to_administrator(apps, schema_editor):
    """Give the Administrator preset the new capability.

    0002 defined Administrator as the role holding every capability, so a new
    one belongs in it. Without this the section ships dead for everyone but
    superusers: the board would render and no one could create a task in it.

    Only the Administrator preset is touched. Editor, Marketing and Support
    are scoped roles and assigning work is not part of any of them, so they
    are left alone for an administrator to extend deliberately.

    The permission row is normally created by the post_migrate signal, which
    has not run yet when this migration executes, so it is created here if
    absent. get_or_create keeps that idempotent when post_migrate later
    reaches the same row.
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
    """Take the capability back off the group, leaving the group itself alone.

    Deleting the permission row outright would cascade to every group and
    user that had been granted it by hand, so a rollback would quietly
    discard an administrator's own configuration. Only the grant this
    migration made is undone.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    permission = Permission.objects.filter(
        codename=CODENAME, content_type__app_label="staff"
    ).first()
    group = Group.objects.filter(name="Administrator").first()
    if permission is not None and group is not None:
        group.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0006_alter_staffcapability_options"),
        ("auth", "__first__"),
        ("contenttypes", "__first__"),
    ]

    operations = [
        migrations.RunPython(grant_to_administrator, revoke_from_administrator),
    ]
