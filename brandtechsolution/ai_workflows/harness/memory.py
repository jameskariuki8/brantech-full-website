"""One memory, three layers.

Memory was in three places that did not know about each other: a checkpointer
used only by chat, a singleton row of brand guidelines used only by editorial,
and a pgvector store that was barely used at all -- while the newsroom's
duplicate-coverage check compared the first twenty characters of a title.

The layers stay separate because they answer genuinely different questions:

- **episodic** -- what happened in this thread? (`DjangoCheckpointer`)
- **semantic** -- what do we already know about X? (pgvector)
- **profile**  -- how do we speak, and what do we avoid? (`AgentProfile`)

Writing to semantic memory embeds it. There is no `embed=True` flag, because
an optional embedding is precisely how the current stores drifted apart.
"""
import hashlib
import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from ai_workflows.harness.errors import MemoryUnavailable

logger = logging.getLogger(__name__)


# The default for `recall(scope=...)`, so that "this memory's own scope" and
# "every scope" are different things and neither is spelled None by accident.
OWN_SCOPE = object()


def _as_scopes(scope):
    return [scope] if isinstance(scope, str) else list(scope)


def content_hash(text) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class MemoryRecord:
    """One recalled document, with its score and where the vector came from."""

    def __init__(self, document, score=None, model_id="", provider=""):
        self.document = document
        self.score = score
        self.model_id = model_id
        self.provider = provider

    @property
    def title(self):
        return self.document.title

    @property
    def text(self):
        return self.document.text

    def __repr__(self):
        return f"<MemoryRecord {self.document.title[:40]!r} score={self.score}>"


class Memory:
    """The facade every agent uses.

    `embedder` is injected so tests do not need a provider and so the
    embedding client is a dependency rather than a hidden import. It is
    resolved lazily: constructing a Memory must not require a working API key,
    or importing an agent would.
    """

    def __init__(self, embedder=None, scope="default"):
        self._embedder = embedder
        self._embedder_resolved = embedder is not None

        # What this memory writes to, and what it reads from unless a caller
        # says otherwise. Two agents with different scopes do not see each
        # other's documents, which is the difference between the newsroom
        # searching its own back catalogue and the newsroom searching every
        # chat transcript the assistant ever saved.
        self.scope = scope

    # ------------------------------------------------------------------
    # semantic
    # ------------------------------------------------------------------

    @property
    def embedder(self):
        if not self._embedder_resolved:
            from ai_workflows.harness.llm import get_embedder

            self._embedder = get_embedder()
            self._embedder_resolved = True
        return self._embedder

    def _active_space(self):
        from knowledge_base.models import EmbeddingSpace

        space = EmbeddingSpace.active()
        if space is None:
            raise MemoryUnavailable(
                "no active embedding space; run the backfill migration or "
                "activate a space before using semantic memory"
            )
        return space

    def remember(self, text, *, title="", kind="document", obj=None, metadata=None):
        """Store `text` and embed it.

        Embedding on write, not on request: the optional path is how
        `BlogPost.embedding` came to be written only by a management command
        and went stale from the first edit onwards.

        Unchanged text is not re-embedded. The content hash makes a repeated
        save free rather than another paid call.
        """
        from knowledge_base.models import Embedding, MemoryDocument

        space = self._active_space()
        digest = content_hash(text)

        lookup = {"content_type": None, "object_id": None}
        if obj is not None:
            lookup = {
                "content_type": ContentType.objects.get_for_model(obj.__class__),
                "object_id": obj.pk,
            }

        with transaction.atomic():
            if obj is not None:
                document, _ = MemoryDocument.objects.get_or_create(
                    **lookup,
                    defaults={"scope": self.scope, "kind": kind,
                              "title": title[:300], "text": text,
                              "metadata": metadata or {}, "content_hash": digest},
                )
            else:
                document = MemoryDocument.objects.create(
                    scope=self.scope, kind=kind, title=title[:300], text=text,
                    metadata=metadata or {}, content_hash=digest,
                )

            already = Embedding.objects.filter(space=space, document=document).exists()
            if already and document.content_hash == digest:
                return MemoryRecord(document)

            document.title = title[:300] or document.title
            document.text = text
            document.content_hash = digest
            if metadata:
                document.metadata = metadata
            document.save()

        vector = self._embed(text)

        Embedding.objects.update_or_create(
            space=space, document=document,
            defaults={
                "provider": space.provider,
                "model_id": space.model_id,
                "dimensions": space.dimensions,
                "vector": vector,
            },
        )
        return MemoryRecord(document, model_id=space.model_id, provider=space.provider)

    def recall(self, query, *, kind=None, limit=5, record_usage=True,
               scope=OWN_SCOPE):
        """The most similar documents in the active space.

        Only ever the active space. A half-built space must not leak into
        results, and merging scores across two spaces is unsound -- they share
        no scale, so the merge would be arbitrary.

        Scoped to this memory's own corpus by default. A caller that genuinely
        wants everything passes `scope=None` and has to mean it; one that wants
        several passes a list. Merging *scopes* is sound in a way merging spaces
        is not -- the vectors are comparable -- so this is a choice about what
        the caller should see, not about whether the numbers mean anything.

        Retrieval is counted here because this is the one chokepoint every
        semantic lookup passes through. After a few weeks that counter says
        which documents matter far better than view counts do, because it
        measures what the agents use rather than what humans clicked -- and it
        is the input to deciding what gets re-embedded first when the model
        changes.
        """
        from pgvector.django import CosineDistance

        from knowledge_base.models import Embedding, MemoryDocument

        space = self._active_space()
        vector = self._embed(query)

        rows = (
            Embedding.objects.filter(space=space)
            .select_related("document")
            .annotate(distance=CosineDistance("vector", vector))
            .order_by("distance")
        )

        if scope is OWN_SCOPE:
            scope = self.scope
        if scope is not None:
            rows = rows.filter(document__scope__in=_as_scopes(scope))

        if kind:
            rows = rows.filter(document__kind=kind)

        results = list(rows[:limit])

        if record_usage and results:
            self._record_usage([r.document_id for r in results])

        return [
            MemoryRecord(
                row.document,
                score=1.0 - float(row.distance),
                model_id=row.model_id,
                provider=row.provider,
            )
            for row in results
        ]

    @staticmethod
    def _record_usage(document_ids):
        """Count a retrieval without racing other workers.

        An F() update rather than read-modify-write: two workers recalling the
        same document concurrently would otherwise each read the same count and
        write the same increment, losing one.
        """
        from django.db.models import F

        from knowledge_base.models import MemoryDocument

        MemoryDocument.objects.filter(id__in=document_ids).update(
            retrieval_count=F("retrieval_count") + 1,
            last_retrieved_at=timezone.now(),
        )

    def _embed(self, text):
        try:
            return self.embedder.embed_query(text or "")
        except Exception as exc:  # noqa: BLE001
            raise MemoryUnavailable(f"could not embed: {exc}") from exc

    def forget(self, obj):
        """Drop what is remembered about `obj`."""
        from knowledge_base.models import MemoryDocument

        return MemoryDocument.objects.filter(
            content_type=ContentType.objects.get_for_model(obj.__class__),
            object_id=obj.pk,
        ).delete()[0]

    # ------------------------------------------------------------------
    # episodic
    # ------------------------------------------------------------------

    def thread(self, thread_id):
        """The checkpointer for one conversation.

        Unchanged from what the chat assistant already uses -- it was the
        best-built piece of the three stores. It is reachable from here so that
        every agent has one way in.
        """
        from ai_workflows.checkpointer import DjangoCheckpointer

        return DjangoCheckpointer(thread_id)

    # ------------------------------------------------------------------
    # profile
    # ------------------------------------------------------------------

    def profile(self):
        from ai_workflows.models import AgentProfile

        return AgentProfile.load()
