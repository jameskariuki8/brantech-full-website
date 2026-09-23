"""What goes into the window, in what order, and what is dropped first.

The largest lever on output quality had no owner. Retrieval that finds the
right document and then places it fortieth of sixty has not helped anyone.

Three jobs, all here:

- **Order.** Stable content first, volatile content last. This is what makes
  provider prompt caching possible at all -- caching matches on an exact
  prefix, so anything that changes per request must sit after everything that
  does not. `_render_system_prompt` used to put `datetime.now()` at the very
  front and invalidate the cached prefix on every single call.
- **Budget.** A real ceiling, counted rather than guessed.
  `MAX_TOKENS_FOR_TRIMMING = 2000` discarded almost all history in a
  million-token era.
- **Eviction.** What goes when it does not fit -- by salience, not purely by
  recency, so an important fact from ten turns ago outranks small talk from
  two.
"""
import logging
from dataclasses import dataclass, field

from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)

# Tool output is context too. A suite with a fetch tool can return a 200KB
# page into a window that also has to hold the instructions, and without a cap
# one call evicts the prompt that explains what to do with it.
DEFAULT_TOOL_RESULT_CHARS = 4000


def approximate_tokens(text) -> int:
    """Rough token count.

    Deliberately approximate and deliberately local: an exact count means a
    round trip to the provider's tokenizer, which is not worth it for deciding
    whether a message fits. Four characters per token is close enough for
    English prose and errs slightly high, which is the safe direction for a
    budget.
    """
    if text is None:
        return 0
    if not isinstance(text, str):
        text = getattr(text, "content", None) or str(text)
    return (len(text) + 3) // 4


@dataclass
class Fragment:
    """One candidate piece of context.

    `salience` is what makes eviction better than a recency cut: a retrieved
    document that directly answers the question should outlive three turns of
    pleasantries. Ties break towards the more recent fragment.
    """

    content: str
    salience: float = 0.5
    order: int = 0
    kind: str = "history"
    pinned: bool = False


@dataclass
class AssembledContext:
    messages: list
    dropped: list = field(default_factory=list)
    tokens: int = 0

    @property
    def dropped_count(self):
        return len(self.dropped)


def truncate_tool_result(text, limit=DEFAULT_TOOL_RESULT_CHARS):
    """Cap one tool result, saying so rather than silently cutting.

    The marker matters: a model handed a silently truncated document will
    reason about it as though it were complete, and confidently describe a
    conclusion that was in the part it never saw.
    """
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    kept = text[:limit].rstrip()
    omitted = len(text) - len(kept)
    return f"{kept}\n\n[... {omitted} characters omitted; this result was truncated ...]"


class ContextAssembler:
    """Builds the message list for one call.

    The stable/volatile split is the whole design. `persona` and anything
    passed as `stable` go first and must never vary between requests;
    `volatile` goes last and may carry the clock, the turn, per-request ids --
    anything that would otherwise destroy the cached prefix.
    """

    def __init__(self, max_tokens=120_000, counter=approximate_tokens,
                 tool_result_chars=DEFAULT_TOOL_RESULT_CHARS):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.max_tokens = max_tokens
        self.count = counter
        self.tool_result_chars = tool_result_chars

    def assemble(self, persona=None, fragments=(), volatile=(), stable=()):
        """Return an AssembledContext within budget.

        Nothing pinned is ever dropped, and neither is the persona -- running
        without an identity is worse than running with less history. If the
        pinned content alone exceeds the budget it is kept and a warning is
        logged, because silently truncating an instruction is how an agent
        starts ignoring a rule nobody removed.
        """
        head = []
        if persona is not None:
            head.append(SystemMessage(content=persona.render()))
        head.extend(SystemMessage(content=text) for text in stable)

        used = sum(self.count(m.content) for m in head)
        used += sum(self.count(item) for item in volatile)

        if used > self.max_tokens:
            logger.warning(
                "[context] fixed content is %s tokens against a %s budget; "
                "keeping it and exceeding the budget rather than cutting "
                "instructions",
                used, self.max_tokens,
            )

        # Highest salience first, most recent breaking ties. Sorting by
        # salience alone would make eviction order unstable between equally
        # salient fragments.
        ranked = sorted(
            fragments, key=lambda f: (f.pinned, f.salience, f.order), reverse=True
        )

        kept, dropped = [], []
        for fragment in ranked:
            cost = self.count(fragment.content)
            if fragment.pinned or used + cost <= self.max_tokens:
                kept.append(fragment)
                used += cost
            else:
                dropped.append(fragment)

        # Restore chronological order for what survived: the model reads a
        # conversation, not a ranking.
        kept.sort(key=lambda f: f.order)

        messages = list(head)
        messages.extend(SystemMessage(content=f.content) for f in kept)
        messages.extend(SystemMessage(content=text) for text in volatile)

        if dropped:
            logger.info("[context] dropped %s fragment(s) to fit the budget", len(dropped))

        return AssembledContext(messages=messages, dropped=dropped, tokens=used)
