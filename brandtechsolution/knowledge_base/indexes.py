"""The vector index, and why there wasn't one.

Every `recall()` in this codebase has been a sequential scan. `Embedding.vector`
is a bare `vector` column with no declared width -- deliberately, so one table
can hold two spaces during a migration -- and Postgres will not build an HNSW
index on a column whose dimensions it does not know:

    column does not have dimensions

`models.py` predicted the fix and it turns out to be right: a partial index per
space, over a cast expression, rather than a schema redesign.

    CREATE INDEX ... USING hnsw ((vector::vector(768)) vector_cosine_ops)
    WHERE space_id = 3

Partial because a space is the unit of comparability and queries never cross
one; the cast supplies the width the column withholds. The catch is that an
expression index is only used by a query carrying the *same* expression, which
is why `Memory.recall` casts too -- the two have to be written together or the
index is built and never read.

**The limit that decides the whole design.** pgvector caps HNSW at 2000
dimensions, and the active space is 3072 -- the native width of
gemini-embedding-001. So the existing space cannot be indexed at all, at any
effort. `halfvec`, which raises the ceiling to 4000, arrived in pgvector 0.7
and this server is 0.6.

That leaves one honest route: a space narrow enough to index. The model is
trained with Matryoshka representation learning, so asking it for 768 or 1536
dimensions is a supported truncation rather than a lossy hack -- and a narrower
space is a smaller table and a faster scan even before the index. Getting there
means re-embedding the corpus, which is what `harness/reembed.py` is for.
"""
import logging

from django.db import connection, transaction

logger = logging.getLogger(__name__)

# pgvector's hard ceiling for an hnsw index over a `vector` column. Not a
# tuning knob: `create index` fails outright above it.
HNSW_MAX_DIMENSIONS = 2000

# Build-time quality/effort. pgvector's defaults are m=16, ef_construction=64;
# these are one step up, which costs build time on a corpus this size (seconds)
# and buys recall at query time.
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 100


def table_name():
    from knowledge_base.models import Embedding

    return Embedding._meta.db_table


def index_name(space):
    return f"kb_embedding_space{space.pk}_hnsw"


def can_index(space):
    """Whether an index is possible for this space's width."""
    return bool(space.dimensions) and space.dimensions <= HNSW_MAX_DIMENSIONS


def why_not(space):
    """A sentence an operator can act on, or "" when it can be indexed."""
    if not space.dimensions:
        return "the space does not record its dimensions"
    if space.dimensions > HNSW_MAX_DIMENSIONS:
        return (
            f"{space.dimensions} dimensions exceeds pgvector's hnsw limit of "
            f"{HNSW_MAX_DIMENSIONS}; re-embed into a narrower space "
            f"(`manage.py reembed --dimensions 1536`) to get an index"
        )
    return ""


def index_exists(space):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s", [index_name(space)]
        )
        return cursor.fetchone() is not None


def ensure_index(space, *, concurrently=True):
    """Build the partial HNSW index for `space`, if one is possible.

    Returns the index name, or None when the space is too wide. Never raises
    for a space that cannot be indexed: an unindexable space still works, it
    just scans, and a migration should not fail because the destination is
    merely slow.
    """
    if not can_index(space):
        logger.warning("[index] not indexing space %s: %s", space.pk, why_not(space))
        return None

    if index_exists(space):
        return index_name(space)

    # CONCURRENTLY cannot run inside a transaction, and it is the difference
    # between a brief lock and blocking every write to the memory table for the
    # duration of the build.
    inside_transaction = connection.in_atomic_block
    if concurrently and inside_transaction:
        logger.info(
            "[index] building space %s's index without CONCURRENTLY: already "
            "inside a transaction", space.pk,
        )
    use_concurrently = concurrently and not inside_transaction

    sql = (
        f"CREATE INDEX {'CONCURRENTLY ' if use_concurrently else ''}"
        f"IF NOT EXISTS {index_name(space)} "
        f"ON {table_name()} USING hnsw "
        f"((vector::vector({space.dimensions})) vector_cosine_ops) "
        f"WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION}) "
        f"WHERE space_id = {int(space.pk)}"
    )

    logger.info("[index] building %s", index_name(space))
    with connection.cursor() as cursor:
        cursor.execute(sql)
    return index_name(space)


def drop_index(space):
    name = index_name(space)
    with connection.cursor() as cursor:
        cursor.execute(f"DROP INDEX IF EXISTS {name}")
    return name


def report():
    """Every space, and whether its queries can use an index.

    The question nobody could ask before: "is this search a scan?"
    """
    from knowledge_base.models import EmbeddingSpace

    rows = []
    for space in EmbeddingSpace.objects.all():
        rows.append({
            "space": space,
            "indexable": can_index(space),
            "indexed": index_exists(space) if can_index(space) else False,
            "reason": why_not(space),
            "embeddings": space.embeddings.count(),
        })
    return rows
