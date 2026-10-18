"""Relabel the ContentType rows of the models folded into ``editorial``.

Eleven models used to belong to the ``trends``, ``research``,
``media_generation``, ``analytics``, ``approval`` and ``publishing`` apps.
Rows that point at their ContentType (``knowledge_base.MemoryDocument``'s
generic FK, auth ``Permission`` and admin ``LogEntry``) must keep pointing at
the *same* row, so the existing rows are relabelled in place instead of letting
Django create fresh ``editorial`` rows and orphan the old ones.

Fresh databases have no such rows, so the migration is a no-op there.
"""

from django.conf import settings
from django.db import migrations

# (old app label, lower-cased model name)
MOVED_MODELS = [
    ("trends", "trendtopic"),
    ("trends", "competitorsource"),
    ("trends", "competitorarticle"),
    ("trends", "trendprediction"),
    ("research", "researchdossier"),
    ("research", "verifiedfactreport"),
    ("media_generation", "mediaasset"),
    ("analytics", "contentanalytics"),
    ("analytics", "feedbacklooprecord"),
    ("approval", "approvalnotification"),
    ("publishing", "publishinglog"),
]


def _merge_content_type(apps, source, target):
    """Repoint everything that references ``source`` at ``target``, then delete ``source``."""
    MemoryDocument = apps.get_model("knowledge_base", "MemoryDocument")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    LogEntry = apps.get_model("admin", "LogEntry")

    MemoryDocument.objects.filter(content_type=source).update(content_type=target)

    existing = {p.codename: p for p in Permission.objects.filter(content_type=target)}
    for perm in Permission.objects.filter(content_type=source):
        keeper = existing.get(perm.codename)
        if keeper is None:
            perm.content_type = target
            perm.save(update_fields=["content_type"])
            existing[perm.codename] = perm
            continue
        # Duplicate codename: carry group/user grants over, then drop the copy.
        group_through = Group.permissions.through
        for row in group_through.objects.filter(permission_id=perm.pk):
            group_through.objects.get_or_create(
                group_id=row.group_id, permission_id=keeper.pk
            )
        if hasattr(User, "user_permissions"):
            user_through = User.user_permissions.through
            user_fk = next(
                f.name
                for f in user_through._meta.fields
                if f.is_relation and f.name not in ("permission",)
            )
            for row in user_through.objects.filter(permission_id=perm.pk):
                user_through.objects.get_or_create(
                    **{f"{user_fk}_id": getattr(row, f"{user_fk}_id")},
                    permission_id=keeper.pk,
                )
        perm.delete()

    LogEntry.objects.filter(content_type=source).update(content_type=target)
    source.delete()


def _relabel(apps, schema_editor, forward):
    ContentType = apps.get_model("contenttypes", "ContentType")
    manager = ContentType.objects.using(schema_editor.connection.alias)
    for old_label, model in MOVED_MODELS:
        src_label, dst_label = (
            (old_label, "editorial") if forward else ("editorial", old_label)
        )
        source = manager.filter(app_label=src_label, model=model).first()
        if source is None:
            continue
        target = manager.filter(app_label=dst_label, model=model).first()
        if target is None:
            source.app_label = dst_label
            source.save(update_fields=["app_label"])
        else:
            _merge_content_type(apps, source, target)


def relabel_forward(apps, schema_editor):
    _relabel(apps, schema_editor, forward=True)


def relabel_backward(apps, schema_editor):
    _relabel(apps, schema_editor, forward=False)


class Migration(migrations.Migration):

    dependencies = [
        ("editorial", "0001_squashed_consolidation"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("knowledge_base", "0002_embeddingspace_memorydocument_embedding_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(relabel_forward, relabel_backward),
    ]
