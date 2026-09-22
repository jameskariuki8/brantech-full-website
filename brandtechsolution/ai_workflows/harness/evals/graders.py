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

from pydantic import Field

from ai_workflows.harness.contract import AgentOutput
from ai_workflows.harness.persona import Persona


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


# ============================================================
# Graders that use a model
# ============================================================
#
# Deterministic checks catch the failures you can name in a regex. They cannot
# tell you whether an article is any good, and the agent this suite most needs
# to watch -- the writer -- fails in ways no regex describes: a paragraph that
# sounds authoritative about something the report never established, a claim
# sharpened one notch past its evidence.
#
# Two model graders, and the second is the one that matters.


class JudgeVerdict(AgentOutput):
    """What a model grader is asked for."""

    passed: bool = False
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class ModelGrader(Grader):
    """Judge one output against a written rubric.

    Absolute scoring, which is the weaker of the two techniques here: a model
    asked "score this 0-1" drifts between runs, between model versions, and
    with the length of what it is reading, so a change in score is as likely to
    be the judge moving as the agent. Useful for a hard yes/no -- "does this
    contain a statistic the source does not support" -- and not for "is this
    well written".

    The judge runs with `allow_fallback=False`. A grader that quietly changed
    model mid-comparison would make every number it produced unattributable,
    which is the one thing an eval suite must not do.
    """

    def __init__(self, name, rubric, *, role=None, description=""):
        self.name = name
        self.rubric = rubric
        self.description = description
        self._role = role

    def _ask(self, prompt, schema=JudgeVerdict):
        from ai_workflows.harness.contract import ask
        from ai_workflows.harness.llm import ModelRole

        return ask(
            JUDGE_PERSONA, prompt, schema,
            role=self._role or ModelRole.PRECISE,
            agent=f"grader:{self.name}",
            allow_fallback=False,
        )

    def grade(self, output, case) -> Grade:
        from ai_workflows.harness.errors import AgentError

        try:
            verdict = self._ask(
                f"{self.rubric}\n\n"
                f"--- the work to judge ---\n{render_for_judging(output)}"
            )
        except AgentError as exc:
            # Undecided, not zero. A judge that could not run has told us
            # nothing about the agent, and scoring it zero would look exactly
            # like the agent having failed.
            return Grade.undecided(f"the judge could not run: {exc}")

        if verdict.abstained:
            return Grade.undecided(verdict.notes or "the judge declined to rule")

        return Grade(
            score=verdict.score,
            passed=verdict.passed,
            detail=verdict.reasoning,
            meta={"judge": "absolute"},
        )


class PairwiseGrader(Grader):
    """Ask which of two outputs is better, rather than how good one is.

    Preferred over `ModelGrader` wherever a reference exists. A model comparing
    two things is far steadier than one assigning a number to one thing: the
    comparison carries its own scale, so the answer does not drift when the
    judge is swapped or the prompt is reworded. It is also the only honest way
    to ask "did this get worse", which is the question the whole suite exists
    for -- an absolute score means very little and a change means a great deal.

    Position is randomised and the answer mapped back, because judges favour
    whichever they read first and a fixed order bakes that bias into the score.
    """

    def __init__(self, name, criterion, reference, *, description=""):
        self.name = name
        self.criterion = criterion
        self.description = description
        # A callable, so the reference can be looked up when the grader runs
        # rather than captured when the case is declared.
        self._reference = reference

    def grade(self, output, case) -> Grade:
        import random

        from ai_workflows.harness.errors import AgentError

        reference = self._reference(case) if callable(self._reference) else self._reference
        if not reference:
            # No baseline to compare against is not a failing grade. It is the
            # first run, or a new case, and reporting it as a regression would
            # make every new case look like damage.
            return Grade.undecided("no reference output to compare against")

        candidate = render_for_judging(output)
        reference_text = render_for_judging(reference)

        swapped = random.random() < 0.5
        first, second = (
            (reference_text, candidate) if swapped else (candidate, reference_text)
        )

        prompt = (
            f"Two pieces of work, A and B. Judge only this: {self.criterion}\n\n"
            f"--- A ---\n{first}\n\n--- B ---\n{second}\n\n"
            "Answer which is better with `winner`, one of \"A\", \"B\" or "
            "\"tie\". Say \"tie\" when the difference is not real rather than "
            "picking one to be decisive."
        )

        try:
            verdict = ModelGrader(self.name, "")._ask(prompt, PairwiseVerdict)
        except AgentError as exc:
            return Grade.undecided(f"the judge could not run: {exc}")

        if verdict.abstained:
            return Grade.undecided(verdict.notes or "the judge declined to rule")

        winner = (verdict.winner or "tie").strip().upper()
        if winner == "TIE":
            return Grade(score=0.5, passed=True, detail=verdict.reasoning,
                         meta={"judge": "pairwise", "winner": "tie"})

        candidate_label = "B" if swapped else "A"
        candidate_won = winner == candidate_label

        return Grade(
            score=1.0 if candidate_won else 0.0,
            # A tie or a win is not a regression; only a loss is.
            passed=candidate_won,
            detail=verdict.reasoning,
            meta={
                "judge": "pairwise",
                "winner": "candidate" if candidate_won else "reference",
                # Recorded so a reviewer can check the randomisation actually
                # varied, rather than trusting that it did.
                "candidate_shown_as": candidate_label,
            },
        )


class PairwiseVerdict(AgentOutput):
    winner: str = "tie"
    reasoning: str = ""


JUDGE_PERSONA = Persona(
    name="grader",
    role="a careful evaluator of technology journalism",
    directives=(
        "Judge only what you were asked to judge, and ignore everything else "
        "about the work.",
        "Give the specific sentence or figure that decided it, not a summary.",
        "Say so when the difference is not real, rather than manufacturing one "
        "to sound decisive.",
    ),
    constraints=(
        "Do not reward length, confidence or polish on their own.",
        "Do not penalise a piece for declining to assert something it could "
        "not support -- that is the behaviour being encouraged.",
        "Decline rather than guessing when you cannot tell.",
    ),
)


def render_for_judging(output, limit=12_000):
    """Flatten an agent output into something a judge can read.

    Model objects become their fields; everything else becomes its string. The
    cap is not politeness: a judge handed thirty thousand characters grades the
    beginning and skims the rest, which shows up as a quality score that
    tracks length.
    """
    if output is None:
        return ""

    if hasattr(output, "model_dump"):
        data = output.model_dump()
        rendered = "\n\n".join(
            f"## {key}\n{value}" for key, value in data.items()
            if value not in (None, "", [], {})
        )
    elif isinstance(output, dict):
        rendered = "\n\n".join(f"## {k}\n{v}" for k, v in output.items() if v)
    elif hasattr(output, "_meta") and hasattr(output._meta, "fields"):
        rendered = _render_row(output)
    else:
        rendered = str(output)

    return rendered[:limit]


# Bookkeeping rather than content. A judge reading these is reading the
# database, not the writing.
_NOT_CONTENT = {"slug", "status", "is_approved", "author", "created_at",
                "updated_at", "published_at"}


def _render_row(instance):
    """A model row's own text, field by field.

    The newsroom's pipeline methods save what they produce and return the row,
    so an eval case's output is a `BlogPost`, not a pydantic object -- and
    `str()` on one of those is its title. That is what was being stored: a run
    kept sixty to a hundred characters per case, the pairwise judge compared
    two titles and called it prose, and "here is what changed" could not be
    answered from the record because the record was one line.
    """
    from django.db.models import CharField, JSONField, TextField

    parts = []
    for field in instance._meta.fields:
        if not isinstance(field, (CharField, TextField, JSONField)):
            continue
        # A field with choices is a state machine, not writing.
        if field.name in _NOT_CONTENT or getattr(field, "choices", None):
            continue

        value = getattr(instance, field.name, None)
        if value in (None, "", [], {}):
            continue
        parts.append(f"## {field.name}\n{value}")

    return "\n\n".join(parts)
