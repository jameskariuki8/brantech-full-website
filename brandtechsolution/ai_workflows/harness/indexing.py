"""Keeping stored vectors current.

`BlogPost.embedding` and `Project.embedding` were only ever written by the
`init_vector_stores` management command. There was no save hook, so every
vector was stale from the first edit until somebody remembered to re-run it by
hand -- and a search over stale vectors does not fail, it just quietly returns
the wrong thing.

Queued on commit, so the worker cannot read a row that the transaction has not
yet made visible.
"""
import logging

from django.db import transaction

from ai_workflows.harness.memory import content_hash

logger = logging.getLogger(__name__)


def queue_embedding(obj, *, kind, title, text):
    """Schedule `obj` to be embedded once the current transaction commits."""
    from ai_workflows.tasks import embed_object_task

    meta = obj._meta
    transaction.on_commit(lambda: embed_object_task.delay(
        meta.app_label, meta.model_name, obj.pk, kind, title or "", text or "",
    ))


def text_for(obj, text_field="content"):
    """The text to embed for `obj`.

    `get_embedding_text()` when the model defines one, because those builders
    fold in the title, category and tags -- a project matched on its
    technologies rather than only on its prose. Falling back to a single field
    would silently embed less than the old management command did.
    """
    builder = getattr(obj, "get_embedding_text", None)
    if callable(builder):
        try:
            return builder() or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[indexing] %s.get_embedding_text() failed, falling back to %s: %s",
                obj.__class__.__name__, text_field, exc,
            )
    return getattr(obj, text_field, "") or ""


def forget(obj):
    """Drop `obj` from semantic memory.

    `MemoryDocument` points at its object through a content type and an id,
    which is not a foreign key, so nothing cascades. Without this, deleting a
    post leaves it in the corpus and the assistant keeps answering from
    content that no longer exists -- and unpublishing it does the same, which
    is worse, because that content was deliberately withdrawn.
    """
    from ai_workflows.harness.memory import Memory

    try:
        return Memory(scope="site").forget(obj)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[indexing] could not forget %s #%s: %s",
                       obj.__class__.__name__, obj.pk, exc)
        return 0


def index_on_save(obj, *, kind, title_field="title", text_field="content"):
    """Queue an embedding for `obj` unless its text is unchanged.

    The hash check happens here rather than in the task so an unchanged save --
    publishing a post, toggling `featured` -- does not even enqueue work. The
    task checks again, because the row can change between enqueue and run.
    """
    from knowledge_base.models import MemoryDocument
    from django.contrib.contenttypes.models import ContentType

    text = text_for(obj, text_field)
    title = getattr(obj, title_field, "") or ""

    digest = content_hash(text)
    existing = MemoryDocument.objects.filter(
        content_type=ContentType.objects.get_for_model(obj.__class__),
        object_id=obj.pk,
    ).values_list("content_hash", flat=True).first()

    if existing == digest:
        return False

    queue_embedding(obj, kind=kind, title=title, text=text)
    return True
