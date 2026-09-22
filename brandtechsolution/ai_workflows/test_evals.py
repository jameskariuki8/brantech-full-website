"""The eval framework itself.

These are tests, not evals: they check the machinery runs correctly, which is
a different question from whether the agents produce good output. The suite
being tested is the thing that answers the second question, so it has to be
trustworthy on the first.
"""
from contextlib import contextmanager
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from ai_workflows.harness.evals.cases import CaseRegistry, EvalCase
from ai_workflows.harness.evals.graders import (
    DeterministicGrader,
    Grade,
    quantitative_claims,
    unsourced_claims,
)
from ai_workflows.harness.evals.runner import EvalRunner, compare
from ai_workflows.models import EvalResult, EvalRun


@contextmanager
def _no_stub(_response):
    """Stand-in for the model stub, for cases that do not need one."""
    yield None


class GradeTests(TestCase):
    def test_undecided_is_not_zero(self):
        """"Could not tell" and "wrong" are different findings."""
        self.assertIsNone(Grade.undecided().score)
        self.assertEqual(Grade.bad().score, 0.0)
        self.assertIsNone(Grade.undecided().passed)
        self.assertIs(Grade.bad().passed, False)

    def test_a_deterministic_grader_accepts_a_bare_bool(self):
        grader = DeterministicGrader("truthy", lambda output, case: bool(output))
        self.assertIs(grader.grade(1, None).passed, True)
        self.assertIs(grader.grade(0, None).passed, False)

    def test_a_deterministic_grader_accepts_a_grade(self):
        grader = DeterministicGrader("explains", lambda o, c: Grade.bad("because"))
        grade = grader.grade(None, None)
        self.assertIs(grade.passed, False)
        self.assertEqual(grade.detail, "because")


class QuantitativeClaimTests(TestCase):
    def test_it_finds_the_kind_of_figure_that_gets_invented(self):
        text = "a 40% improvement, 3x faster, and 2 million users"
        found = " ".join(quantitative_claims(text)).lower()
        self.assertIn("40%", found)
        self.assertIn("3x", found)
        self.assertIn("2 million", found)

    def test_it_ignores_years_and_small_counts(self):
        """"2024" and "3 modules" are not the failure mode being watched."""
        self.assertEqual(quantitative_claims("in 2024 across 3 modules"), [])

    def test_a_claim_present_in_the_sources_is_not_flagged(self):
        self.assertEqual(
            unsourced_claims("throughput rose 40%", "the vendor reported 40% higher throughput"),
            [],
        )

    def test_a_claim_absent_from_the_sources_is_flagged(self):
        self.assertEqual(
            unsourced_claims("throughput rose 40%", "the vendor reported an improvement"),
            ["40%"],
        )


class RegistryTests(TestCase):
    def _case(self, name, agent="a"):
        return EvalCase(name=name, agent=agent, setup=lambda: None, run=lambda f: None)

    def test_cases_are_filterable_by_agent(self):
        registry = CaseRegistry()
        registry.register(self._case("one", "writer"))
        registry.register(self._case("two", "verifier"))
        registry.register(self._case("three", "writer"))

        self.assertEqual(len(registry.for_agent("writer")), 2)
        self.assertEqual(registry.agents(), ["verifier", "writer"])

    def test_a_duplicate_name_is_refused(self):
        """Two cases with one name would silently overwrite each other's score."""
        registry = CaseRegistry()
        registry.register(self._case("dup"))
        with self.assertRaises(ValueError):
            registry.register(self._case("dup"))


class RunnerTests(TestCase):
    """The runner, driven by cases built here rather than the real suite."""

    def _runner(self, registry, **kwargs):
        # `live=True` because these fixtures declare no `model_response`, which
        # is what marks a case as needing a real call. They do not make one --
        # their `run` is a plain function -- but the runner cannot know that,
        # and inferring "live" from "unstubbed" is the conservative way round:
        # a case that might call a model and was forgotten about should be
        # skipped by default rather than billed.
        kwargs.setdefault("live", True)
        runner = EvalRunner(stub=_no_stub, **kwargs)
        # The runner loads the real suite; point it at a built one instead.
        from unittest.mock import patch
        self._patched = patch(
            "ai_workflows.harness.evals.runner.load_cases", return_value=registry,
        )
        self._patched.start()
        self.addCleanup(self._patched.stop)
        return runner

    def _passing_case(self):
        return EvalCase(
            name="passes", agent="demo",
            setup=lambda: {"v": 1}, run=lambda f: f["v"],
            graders=[DeterministicGrader("is_one", lambda o, c: o == 1)],
        )

    def test_a_run_records_a_result_per_grader(self):
        registry = CaseRegistry()
        registry.register(self._passing_case())
        run = self._runner(registry).run()

        self.assertEqual(run.status, "complete")
        self.assertEqual(run.agents, ["demo"])
        self.assertEqual(run.results.count(), 1)
        self.assertEqual(run.score, 1.0)

    def test_several_samples_produce_several_results(self):
        registry = CaseRegistry()
        registry.register(self._passing_case())
        run = self._runner(registry, samples=4).run()

        self.assertEqual(run.results.count(), 4)
        self.assertEqual(sorted(r.sample for r in run.results.all()), [0, 1, 2, 3])

    def test_each_sample_gets_a_fresh_fixture(self):
        """Agents that cache on an existing row would otherwise flatten the spread."""
        built = []
        registry = CaseRegistry()
        registry.register(EvalCase(
            name="counts", agent="demo",
            setup=lambda: built.append(1) or len(built),
            run=lambda f: f,
            graders=[DeterministicGrader("any", lambda o, c: True)],
        ))
        self._runner(registry, samples=3).run()
        self.assertEqual(len(built), 3)

    def test_an_agent_that_raises_is_recorded_as_undecided_not_zero(self):
        def boom(_fixture):
            raise RuntimeError("the agent fell over")

        registry = CaseRegistry()
        registry.register(EvalCase(
            name="raises", agent="demo", setup=lambda: None, run=boom,
            graders=[DeterministicGrader("never_runs", lambda o, c: True)],
        ))
        run = self._runner(registry).run()

        result = run.results.get()
        self.assertIsNone(result.score)
        self.assertIsNone(result.passed)
        self.assertIn("the agent fell over", result.detail)
        # An agent that crashed has not scored zero; it has not been graded.
        self.assertIsNone(run.score)

    def test_a_failing_grader_scores_zero(self):
        registry = CaseRegistry()
        registry.register(EvalCase(
            name="fails", agent="demo", setup=lambda: None, run=lambda f: "wrong",
            graders=[DeterministicGrader("is_right", lambda o, c: o == "right")],
        ))
        run = self._runner(registry).run()
        self.assertEqual(run.score, 0.0)
        self.assertIs(run.results.get().passed, False)

    def test_an_empty_selection_is_an_error_not_a_perfect_score(self):
        registry = CaseRegistry()
        registry.register(self._passing_case())
        with self.assertRaises(ValueError):
            self._runner(registry).run(agents=["nobody"])


class CompareTests(TestCase):
    def _run_with(self, agent, score, **kwargs):
        run = EvalRun.objects.create(agents=[agent], status="complete", **kwargs)
        EvalResult.objects.create(run=run, agent=agent, case="c", grader="g", score=score)
        return run

    def test_a_drop_is_reported_as_a_negative_delta(self):
        baseline = self._run_with("demo", 1.0, is_baseline=True)
        now = self._run_with("demo", 0.5)
        self.assertEqual(compare(now, baseline)["demo"]["delta"], -0.5)

    def test_a_missing_side_is_not_comparable_rather_than_zero(self):
        baseline = self._run_with("demo", 1.0, is_baseline=True)
        now = EvalRun.objects.create(agents=["demo"], status="complete")
        self.assertIsNone(compare(now, baseline)["demo"]["delta"])


class CommandTests(TestCase):
    """The real suite, through the real command."""

    def test_the_suite_passes_against_the_current_agents(self):
        out = StringIO()
        call_command("run_evals", "--label", "test", stdout=out)
        printed = out.getvalue()
        self.assertIn("fact_verifier", printed)
        self.assertIn("verifier.rejects_planted_contradiction", printed)
        self.assertNotIn("FAIL", printed)

    def test_an_unknown_agent_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command("run_evals", "--agent", "nonexistent", stdout=StringIO())

    def test_comparing_without_a_baseline_says_so_rather_than_crashing(self):
        out = StringIO()
        call_command("run_evals", "--compare", stdout=out)
        self.assertIn("No baseline", out.getvalue())

    def test_the_run_is_persisted(self):
        call_command("run_evals", "--label", "persisted", stdout=StringIO())
        run = EvalRun.objects.get(label="persisted")
        self.assertEqual(run.status, "complete")
        self.assertTrue(run.results.exists())
        self.assertEqual(run.score, 1.0)
