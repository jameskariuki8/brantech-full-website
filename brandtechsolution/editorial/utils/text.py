"""
Fitting model-written text into fixed-width columns.
"""
import logging

logger = logging.getLogger(__name__)


def fit_to_column(model, field: str, text: str) -> str:
    """Cut `text` down to what `model.field` can hold.

    A language model is not a reliable judge of length. A headline or a meta
    description that comes back a few characters over its CharField raises
    DataError on save, and it does so after the draft has been paid for, so a
    whole article is thrown away over its metadata. Losing the end of a meta
    description is the cheaper failure.

    The limit is read off the field, so widening the column is enough to change
    the behaviour. Cuts on a word boundary when one is near enough to the end
    to be worth keeping, the same rule as PublishingAgent._fit_title.
    """
    limit = model._meta.get_field(field).max_length
    text = (text or "").strip()
    if not limit or len(text) <= limit:
        return text

    clipped = text[:limit].rstrip()
    cut = clipped.rfind(' ')
    if cut > limit * 0.75:
        clipped = clipped[:cut].rstrip()
    logger.warning(
        "%s.%s was %d characters, over its limit of %d; truncated.",
        model.__name__, field, len(text), limit,
    )
    return clipped
