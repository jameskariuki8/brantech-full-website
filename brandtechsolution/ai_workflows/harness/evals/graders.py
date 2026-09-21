"""Graders: how an agent's output is scored.

A grader takes whatever the agent produced and returns a `Grade`. It never
raises for a bad output -- a bad output is the thing being measured -- but it
does raise if it cannot grade at all, because a grader that silently returns
"pass" when it is broken is worse than no grader.
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Grade:
    """One verdict.

    `score` is None when the grader could not reach a verdict at all, which is
    deliberately distinct from 0.0 -- "could not tell" and "wrong" are
    different findings and averaging them together hides the first.
    """

    score: float | None
    passed: bool | None = None
    detail: str = ""
    meta: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, detail: str = "", **meta):
        return cls(score=1.0, passed=True, detail=detail, meta=meta)

    @classmethod
    def bad(cls, detail: str = "", **meta):
        return cls(score=0.0, passed=False, detail=detail, meta=meta)

    @classmethod
    def undecided(cls, detail: str = "", **meta):
        return cls(score=None, passed=None, detail=detail, meta=meta)


class Grader(ABC):
    """Scores one agent output."""

    name: str = "grader"

    @abstractmethod
    def grade(self, output: Any, case) -> Grade:
        """Return a Grade for `output`, produced by running `case`."""


class DeterministicGrader(Grader):
    """A grader that checks a fact with a predicate, not a model.

    Takes a callable returning either a bool or a `Grade`, so simple checks
    stay one line while a check that wants to explain itself can.
    """

    def __init__(self, name, check, description=""):
        self.name = name
        self._check = check
        self.description = description

    def grade(self, output, case) -> Grade:
        result = self._check(output, case)
        if isinstance(result, Grade):
            return result
        return Grade.ok(self.description) if result else Grade.bad(self.description)


# ============================================================
# Reusable checks
# ============================================================

# Numbers that read as findings: percentages, multipliers, orders of
# magnitude. Bare years and small counts are excluded because they are rarely
# the fabricated kind -- "2024" and "3 modules" are not the problem;
# "a 40% improvement" is.
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
