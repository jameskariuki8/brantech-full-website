"""Give MemoryDocument a scope, and put the existing rows in the right one.

`Memory(scope=...)` has been accepted, stored and ignored since step 2, so
every caller that thought it was scoping its reads was reading everything. This
adds the column and backfills it.

Existing documents come from the step 2 backfill of BlogPost and Project, so
they are site content and belong in `site` -- the scope the chat assistant
reads. Leaving them in `default` would put them somewhere nothing looks, which
is a quieter kind of wrong than the bug being fixed.
"""
from django.db import migrations, models


def to_site(apps, schema_editor):
    MemoryDocument = apps.get_model("knowledge_base", "MemoryDocument")
    MemoryDocument.objects.filter(scope="default").update(scope="site")


def to_default(apps, schema_editor):
    MemoryDocument = apps.get_model("knowledge_base", "MemoryDocument")
    MemoryDocument.objects.filter(scope="site").update(scope="default")


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge_base", "0003_backfill_embeddings"),
    ]

    operations = [
        migrations.AddField(
            model_name="memorydocument",
            name="scope",
            field=models.CharField(db_index=True, default="default", max_length=40),
        ),
        migrations.RunPython(to_site, to_default),
    ]
