"""Runs the eval suite and records what it found.

Each case is set up, run `samples` times, and graded by each of its graders.
Results go to `EvalRun` / `EvalResult` so a run can be compared against the
one before it -- which is the entire point, since an absolute score means very
little and a change in score means a great deal.
"""
import logging
import subprocess
import traceback

from django.db import transaction
from django.utils import timezone

from ai_workflows.harness.evals.cases import load_cases
from ai_workflows.models import EvalResult, EvalRun

logger = logging.getLogger(__name__)


def _git_sha():
    """Best-effort commit id, so a score can be traced to the code that got it."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL,
        ).strip()[:40]
    except Exception:
        return ""


class EvalRunner:
    """Executes cases against the agents as they currently are.

    The model is stubbed per case. That is not a shortcut around measuring the
    real thing -- it is what makes the measurement mean anything. These cases
    ask what the *agent* does with a given model response ("given the model
    reported a contradiction, does the gate refuse?"), and letting the live
    model decide its own answer would make every run measure a different
    question.

    Cases that must exercise real model output -- prose quality, graded
    pairwise -- are a separate mode and are not stubbed. None exist yet.
    """

    def __init__(self, samples=1, label="", is_baseline=False, stub=None):
        self.samples = max(1, samples)
        self.label = label
        self.is_baseline = is_baseline
        # Injected so tests can supply their own, and so the stub is a
        # dependency of the runner rather than a hidden import.
        self._stub = stub or self._default_stub

    @staticmethod
    def _default_stub(response):
        from editorial.llm_fakes import fake_gemini

        return fake_gemini(response)

    def run(self, agents=None, cases=None):
        registry = load_cases()

        selected = registry.all()
        if agents:
            selected = [c for c in selected if c.agent in agents]
        if cases:
            selected = [c for c in selected if c.name in cases]

        if not selected:
            raise ValueError("no eval cases matched the selection")

        run = EvalRun.objects.create(
            label=self.label,
            is_baseline=self.is_baseline,
            agents=sorted({c.agent for c in selected}),
            samples_per_case=self.samples,
            git_sha=_git_sha(),
        )

        try:
            for case in selected:
                self._run_case(run, case)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            run.status = 'failed'
            run.error = f"{exc}\n{traceback.format_exc()}"
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error', 'finished_at'])
            raise

        run.status = 'complete'
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'finished_at'])
        return run

    def _run_case(self, run, case):
        for sample in range(self.samples):
            # Each sample gets its own fixture. Sharing one would let an agent
            # that caches by input -- several of them look up an `existing` row
            # first -- return sample 0's answer for every later sample, and the
            # spread would read as zero.
            with transaction.atomic():
                fixture = case.setup()

            try:
                if case.model_response is not None:
                    with self._stub(case.model_response):
                        output = case.run(fixture)
                else:
                    output = case.run(fixture)
            except Exception as exc:  # noqa: BLE001
                # An agent that raised has not been graded; that is a finding,
                # not a grade of zero.
                logger.exception("[evals] %s raised on sample %s", case.name, sample)
                EvalResult.objects.create(
                    run=run, agent=case.agent, case=case.name, sample=sample,
                    grader='(raised)', score=None, passed=None,
                    detail=f"{type(exc).__name__}: {exc}",
                )
                continue

            for grader in case.graders:
                grade = grader.grade(output, case)
                EvalResult.objects.create(
                    run=run, agent=case.agent, case=case.name, sample=sample,
                    grader=grader.name, score=grade.score, passed=grade.passed,
                    detail=grade.detail, output=grade.meta or None,
                )


def compare(run, baseline):
    """Per-agent score difference between two runs.

    Returns {agent: {"score": x, "baseline": y, "delta": x - y}}, with None
    where either side has no score -- a missing measurement is reported as
    missing rather than silently treated as zero.
    """
    agents = sorted(set(run.agents) | set(baseline.agents))
    out = {}
    for agent in agents:
        now = run.score_for(agent)
        was = baseline.score_for(agent)
        out[agent] = {
            "score": now,
            "baseline": was,
            "delta": None if (now is None or was is None) else now - was,
        }
    return out
