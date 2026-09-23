"""Index the site's content into semantic memory.

This command used to write `BlogPost.embedding` and `Project.embedding` --
single columns holding one vector each, with no record of which model produced
them. Those columns could not survive a change of embedding model and were a
second corpus alongside the one `Memory` maintains, so the site had two
half-populated indexes and the assistant answered from whichever one its tools
happened to read.

It now writes the same store everything else uses, which means the content
gets provenance, re-embedding and the vector index along with it.

Saves keep themselves indexed through `ai_workflows/signals.py`. This is for
the rows that already existed when that hook was connected, and for repairing
a corpus after a space is rebuilt.
"""
from django.core.management.base import BaseCommand

from ai_workflows.harness.errors import AgentError
from ai_workflows.harness.indexing import forget, text_for
from ai_workflows.harness.memory import Memory, content_hash

# (model, kind, text field, a filter for what may be indexed at all)
SOURCES = [
    ("brand.BlogPost", "blog_post", "content", {"status": "published"}),
    ("brand.Project", "project", "description", {}),
]


class Command(BaseCommand):
    help = "Index blog posts and projects into semantic memory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Re-embed even rows whose text is unchanged.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Say what would be embedded without paying for it.",
        )

    def handle(self, *args, **options):
        from django.apps import apps
        from knowledge_base.models import MemoryDocument

        memory = Memory(scope="site")

        try:
            space = memory._active_space()
        except AgentError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        self.stdout.write(f"Indexing into {space}\n")

        indexed = skipped = removed = failed = 0

        for label, kind, text_field, allowed in SOURCES:
            model = apps.get_model(label)
            self.stdout.write(f"\n{model._meta.verbose_name_plural.title()}")

            # Anything excluded by the filter must be actively removed, not
            # merely left unindexed: a post that was published when it was
            # last indexed and is a draft now is still in the corpus.
            if allowed:
                for row in model.objects.exclude(**allowed).iterator():
                    if forget(row):
                        removed += 1
                        self.stdout.write(f"  - withdrew {row}")

            rows = model.objects.filter(**allowed) if allowed else model.objects.all()
            total = rows.count()

            for position, row in enumerate(rows.iterator(), start=1):
                text = text_for(row, text_field)
                if not text.strip():
                    self.stdout.write(f"  [{position}/{total}] {row} -- no text, skipped")
                    skipped += 1
                    continue

                if not options["force"] and self._unchanged(row, text, space):
                    skipped += 1
                    continue

                if options["dry_run"]:
                    self.stdout.write(f"  [{position}/{total}] would embed: {row}")
                    indexed += 1
                    continue

                try:
                    memory.remember(
                        text,
                        title=getattr(row, "title", "") or str(row),
                        kind=kind,
                        obj=row,
                    )
                except AgentError as exc:
                    # One row failing must not abandon the rest: a partial
                    # index is worth more than none, and the command is safe
                    # to re-run for whatever did not land.
                    failed += 1
                    self.stderr.write(self.style.ERROR(f"  [{position}/{total}] {row}: {exc}"))
                    continue

                indexed += 1
                self.stdout.write(f"  [{position}/{total}] {row}")

        verb = "would index" if options["dry_run"] else "indexed"
        self.stdout.write("")
        summary = f"{verb} {indexed}, skipped {skipped} unchanged, withdrew {removed}"
        if failed:
            self.stdout.write(self.style.ERROR(f"{summary}, {failed} failed"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))

    @staticmethod
    def _unchanged(row, text, space):
        """Whether this row is already embedded, from this text, in this space.

        All three have to hold. Matching text in a *retired* space is not an
        index -- it is the reason a cutover would look complete while queries
        found nothing.
        """
        from django.contrib.contenttypes.models import ContentType
        from knowledge_base.models import MemoryDocument

        document = MemoryDocument.objects.filter(
            content_type=ContentType.objects.get_for_model(row.__class__),
            object_id=row.pk,
        ).first()

        return (
            document is not None
            and document.content_hash == content_hash(text)
            and document.embeddings.filter(space=space).exists()
        )
