"""Seed the shared profile from EditorialMemory, if one exists.

Adopting a single brand voice must not change what the writer produces, so the
profile starts as whatever editorial was already using rather than as the
model default.
"""
from django.db import migrations


def seed(apps, schema_editor):
    AgentProfile = apps.get_model("ai_workflows", "AgentProfile")
    EditorialMemory = apps.get_model("editorial", "EditorialMemory")

    existing = EditorialMemory.objects.first()
    defaults = {}
    if existing is not None:
        defaults = {
            "brand_voice": existing.brand_voice,
            "preferred_terminology": existing.preferred_terminology or {},
            "excluded_topics": existing.excluded_topics or [],
        }

    AgentProfile.objects.update_or_create(pk=1, defaults=defaults)


def unseed(apps, schema_editor):
    apps.get_model("ai_workflows", "AgentProfile").objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ai_workflows", "0004_agentprofile"),
        ("editorial", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
