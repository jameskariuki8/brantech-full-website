"""Finding numbers that read as findings.

Lived in `evals/graders.py` until the writer needed it too. Production code
importing from its own eval package would be backwards, and a second copy of
the rule would be worse: the agent would be enforcing one definition of
"invented figure" while the suite measured another, and the two would drift
without either being wrong enough to notice.
"""
import re

# Percentages, multipliers, orders of magnitude. Bare years and small counts
# are excluded because they are rarely the fabricated kind -- "2024" and
# "3 modules" are not the problem; "a 40% improvement" is.
_QUANTITATIVE_CLAIM = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|x\b|×|million|billion|trillion)",
    re.IGNORECASE,
)


def quantitative_claims(text: str) -> list[str]:
    """Every numeric claim in `text` that reads as a statistic."""
    return [m.group(0).strip() for m in _QUANTITATIVE_CLAIM.finditer(text or "")]


def unsourced_claims(text: str, sources_text: str) -> list[str]:
    """Numeric claims present in `text` but absent from its sources.

    A blunt instrument on purpose: it will not catch a rephrased figure, and
    it is not meant to. It catches the specific failure this codebase has
    demonstrated -- an agent with no way to say "I don't know" inventing a
    number to fill a required field.
    """
    haystack = (sources_text or "").lower()
    return [
        claim for claim in quantitative_claims(text)
        if claim.lower() not in haystack
    ]
