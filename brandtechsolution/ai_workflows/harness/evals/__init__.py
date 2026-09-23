"""Evals: does the agent produce good output, not merely any output.

The suite is ordinary Python in this repository, run by `manage.py run_evals`,
with results in Postgres. Nothing here talks to a hosted eval platform.

Two kinds of grader, and the split is not about cost:

- **Deterministic** where the answer is a fact. Did the verifier reject a
  dossier carrying a planted false claim? Is the emitted JSON-LD valid? A
  rubric is a worse instrument for a fact than an assertion is.
- **Pairwise** where the answer is a judgement. Asking a model to rate a draft
  7/10 produces numbers that drift between runs; asking which of two drafts is
  better is markedly more stable, and it is the question every step of the
  harness migration actually asks.
"""
from ai_workflows.harness.evals.cases import EvalCase, registry
from ai_workflows.harness.evals.graders import (
    DeterministicGrader,
    Grade,
    Grader,
)

__all__ = ["EvalCase", "registry", "Grader", "Grade", "DeterministicGrader"]
