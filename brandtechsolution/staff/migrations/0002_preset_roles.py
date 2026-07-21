from django.db import migrations

PRESETS = {
    "Editor": ["manage_blog", "publish_blog", "manage_projects"],
    "Marketing": ["manage_templates", "manage_campaigns", "manage_recipients"],
    "Support": ["view_inbox", "handle_inquiries", "manage_appointments"],
    "Administrator": [
        "manage_blog",
        "publish_blog",
        "manage_projects",
        "manage_appointments",
        "view_inbox",
        "handle_inquiries",
        "manage_templates",
        "manage_campaigns",
        "manage_recipients",
        "send_campaigns",
        "manage_staff",
    ],
}


def create_presets(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    from staff.capabilities import ALL_CAPABILITIES

    content_type, _ = ContentType.objects.get_or_create(
        app_label="staff", model="staffcapability"
    )
    for codename, label in ALL_CAPABILITIES:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=content_type,
            defaults={"name": label},
        )

    for name, codenames in PRESETS.items():
        group, _ = Group.objects.get_or_create(name=name)
        perms = Permission.objects.filter(
            codename__in=codenames, content_type=content_type
        )
        group.permissions.set(perms)


def remove_presets(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=PRESETS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0001_initial"),
        # Permissions are created by a post_migrate signal on contenttypes/auth,
        # so this migration must not run before those apps are fully migrated.
        ("auth", "__first__"),
        ("contenttypes", "__first__"),
    ]

    operations = [
        migrations.RunPython(create_presets, remove_presets),
    ]
