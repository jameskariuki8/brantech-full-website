"""Which memories matter most, for when there is not budget to re-embed them all.

`MemoryDocument.retrieval_count` has been written on every recall since the
memory layer was built and read by nothing. Its docstring says what it is for:

    retrieval counts are the input to the importance score that decides what
    gets re-embedded first when the model changes

This is that score. It exists because changing embedding model is not free --
every document has to be sent to the new model -- and a corpus large enough to
matter is a corpus you may not want to re-embed in one go. Ordering by
importance means a half-finished migration still serves the documents the
agents actually reach for.

Two signals, multiplied rather than added.

**Use**, as `log1p(retrieval_count)`. Logarithmic because the difference
between nought and five retrievals is a real distinction and the difference
between a hundred and a hundred and five is noise. This is the signal nothing
else in the codebase has: view counts measure human attention, and this
measures what the agents reach for.

**Freshness**, as exponential decay since the document was last useful.
Multiplied, not added, so a document nobody has touched in a year sinks however
often it was read back then -- the question is what is worth embedding *now*.

Deliberately not weighted by `kind`. A ranking of which kinds matter would be a
guess dressed as a policy, and the usage signal already answers it from
evidence: if dossiers are reached for more than articles, dossiers score higher
without anyone having decided that they should.
"""
import math

from django.utils import timezone

# How long it takes an untouched document to lose half its score. A month is
# roughly the point at which this newsroom's own coverage stops being current,
# which is the thing the decay is standing in for.
HALF_LIFE_DAYS = 30.0


def importance(document, now=None):
    """A document's score. Higher is re-embedded sooner.

    Never zero, so that even a stale unused document is eventually reached
    rather than being excluded by construction -- a corpus that can never
    finish migrating is a worse failure than a slow one.
    """
    now = now or timezone.now()

    used = math.log1p(max(document.retrieval_count or 0, 0))

    last_useful = (
        document.last_retrieved_at
        or document.updated_at
        or document.created_at
        or now
    )
    age_days = max((now - last_useful).total_seconds() / 86_400.0, 0.0)
    freshness = 0.5 ** (age_days / HALF_LIFE_DAYS)

    # The 1.0 floor on use is what stops a never-retrieved document scoring
    # zero and sorting below every retrieved one regardless of age. A document
    # written this morning has not had the chance to be recalled yet.
    return (1.0 + used) * freshness


def rank(documents, now=None):
    """`documents` most-important first, as a list of (document, score).

    Sorted in Python rather than the database. The expression is a logarithm
    and an exponential over three nullable columns, which SQL can express but
    not legibly, and the queryset is already restricted to documents missing
    from one space. At the point that set is large enough for this to matter,
    the fix is a stored score column updated on recall -- not a cleverer query.
    """
    now = now or timezone.now()
    scored = [(document, importance(document, now)) for document in documents]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def explain(document, now=None):
    """The parts of a document's score, for a command that has to justify itself.

    An operator about to spend money on a partial migration should be able to
    see why these documents were chosen and not those.
    """
    now = now or timezone.now()
    last_useful = (
        document.last_retrieved_at or document.updated_at
        or document.created_at or now
    )
    age_days = max((now - last_useful).total_seconds() / 86_400.0, 0.0)
    return {
        "retrievals": document.retrieval_count or 0,
        "age_days": round(age_days, 1),
        "freshness": round(0.5 ** (age_days / HALF_LIFE_DAYS), 4),
        "score": round(importance(document, now), 4),
    }
