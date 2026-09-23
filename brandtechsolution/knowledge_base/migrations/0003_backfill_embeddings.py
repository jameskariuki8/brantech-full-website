"""Move existing vectors out of the content models and into `Embedding`.

`BlogPost.embedding`, `Project.embedding` and `KnowledgeDocument.embedding`
are single columns, so a row holds exactly one vector and nothing records
which model produced it. This creates the space those vectors belong to, a
`MemoryDocument` per row that has one, and an `Embedding` carrying the vector
with its provenance.

The columns are *not* dropped here. Reading moves to `Embedding` first and the
columns come out in a later migration, so that a backfill problem is
recoverable by rereading the column rather than by re-embedding everything.

Reversible: unapplying copies the vectors back into the columns before the
tables are dropped, so no data is lost in either direction.
"""
from django.db import migrations

# What produced the vectors already in the database. Everything that has ever
# written one did so through ai_workflows/tools.py's get_embeddings(), which
# reads these two settings, so the existing rows all come from this model.
LEGACY_PROVIDER = "gemini"
LEGACY_MODEL = "models/gemini-embedding-001"
LEGACY_DIMENSIONS = 3072

# (app, model, kind, title field, text field)
SOURCES = [
    ("brand", "BlogPost", "blog_post", "title", "content"),
    ("brand", "Project", "project", "title", "description"),
    ("knowledge_base", "KnowledgeDocument", "knowledge_document", "title", "content"),
]


def backfill(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    EmbeddingSpace = apps.get_model("knowledge_base", "EmbeddingSpace")
    MemoryDocument = apps.get_model("knowledge_base", "MemoryDocument")
    Embedding = apps.get_model("knowledge_base", "Embedding")

    space, _ = EmbeddingSpace.objects.get_or_create(
        provider=LEGACY_PROVIDER,
        model_id=LEGACY_MODEL,
        dimensions=LEGACY_DIMENSIONS,
        defaults={"status": "active"},
    )
    # Whatever it was created as, the space holding today's vectors is the one
    # queries must use.
    if space.status != "active":
        space.status = "active"
        space.save()

    for app_label, model_name, kind, title_field, text_field in SOURCES:
        model = apps.get_model(app_label, model_name)
        content_type = ContentType.objects.get_for_model(model)

        for row in model.objects.exclude(embedding=None).iterator():
            document, _ = MemoryDocument.objects.get_or_create(
                content_type=content_type,
                object_id=row.pk,
                defaults={
                    "kind": kind,
                    "title": (getattr(row, title_field, "") or "")[:300],
                    "text": getattr(row, text_field, "") or "",
                },
            )
            Embedding.objects.get_or_create(
                space=space,
                document=document,
                defaults={
                    "provider": LEGACY_PROVIDER,
                    "model_id": LEGACY_MODEL,
                    "dimensions": LEGACY_DIMENSIONS,
                    "vector": row.embedding,
                },
            )


def restore(apps, schema_editor):
    """Copy the vectors back onto the content models.

    Runs before the tables are dropped, so unapplying this migration loses
    nothing -- the columns still exist at this point because the migration that
    removes them is unapplied first.
    """
    ContentType = apps.get_model("contenttypes", "ContentType")
    Embedding = apps.get_model("knowledge_base", "Embedding")

    for app_label, model_name, _kind, _title, _text in SOURCES:
        model = apps.get_model(app_label, model_name)
        content_type = ContentType.objects.get_for_model(model)

        rows = Embedding.objects.filter(
            document__content_type=content_type
        ).select_related("document")

        for embedding in rows.iterator():
            model.objects.filter(pk=embedding.document.object_id).update(
                embedding=embedding.vector
            )


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge_base", "0002_embeddingspace_memorydocument_embedding_and_more"),
        ("contenttypes", "0002_remove_content_type_name"),
        # The vectors being read live on brand's models, so brand's schema has
        # to be in place before this runs.
        ("brand", "0015_seed_showcase_products"),
    ]

    operations = [
        migrations.RunPython(backfill, restore),
    ]
