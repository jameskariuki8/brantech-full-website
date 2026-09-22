"""The eval suite's second half: graders that use a model, and live cases.

The suite started with four deterministic cases against one agent. Two things
were missing, and they are related: the writer had no eval at all, and there
was no way to grade the kind of failure the writer has -- a paragraph that
sounds authoritative about something the report never established. No regex
describes that.
"""
from unittest.mock import patch

from django.test import TestCase

from ai_workflows.harness.errors import ModelUnavailable
from ai_workflows.harness.evals.cases import EvalCase
from ai_workflows.harness.evals.graders import (
    DeterministicGrader,
    Grade,
    JudgeVerdict,
    ModelGrader,
    PairwiseGrader,
    PairwiseVerdict,
    render_for_judging,
)
from ai_workflows.harness.evals.runner import EvalRunner, baseline_output
from ai_workflows.models import EvalResult, EvalRun


def _case(name="c", **kwargs):
    kwargs.setdefault("agent", "writer")
    kwargs.setdefault("setup", lambda: None)
    kwargs.setdefault("run", lambda f: "output")
    kwargs.setdefault("graders", [])
    return EvalCase(name=name, **kwargs)


def _judging(verdict):
    """Pin what the judge says."""
    return patch("ai_workflows.harness.contract.ask", return_value=verdict)


class ModelGraderTests(TestCase):
    RUBRIC = "Does this contain a figure the source does not support?"

    def test_a_verdict_becomes_a_grade(self):
        with _judging(JudgeVerdict(passed=True, score=0.9, reasoning="clean")):
            grade = ModelGrader("judge", self.RUBRIC).grade("some prose", _case())

        self.assertEqual(grade.score, 0.9)
        self.assertTrue(grade.passed)
        self.assertEqual(grade.detail, "clean")

    def test_a_judge_that_cannot_run_is_undecided_not_zero(self):
        """Scoring it zero would look exactly like the agent having failed,
        which is a different and much more alarming finding."""
        with patch("ai_workflows.harness.contract.ask",
                   side_effect=ModelUnavailable("no key")):
            grade = ModelGrader("judge", self.RUBRIC).grade("prose", _case())

        self.assertIsNone(grade.score)
        self.assertIsNone(grade.passed)
        self.assertIn("could not run", grade.detail)

    def test_a_judge_that_declines_is_undecided(self):
        from ai_workflows.harness.contract import OutputStatus

        verdict = JudgeVerdict(status=OutputStatus.INSUFFICIENT_EVIDENCE,
                               notes="cannot tell from this")
        with _judging(verdict):
            grade = ModelGrader("judge", self.RUBRIC).grade("prose", _case())

        self.assertIsNone(grade.score)
        self.assertIn("cannot tell", grade.detail)

    def test_the_judge_must_not_drift_between_models(self):
        """A grader that quietly changed model mid-comparison would make every
        number it produced unattributable, which is the one thing an eval suite
        must not do."""
        with patch("ai_workflows.harness.contract.ask") as ask:
            ask.return_value = JudgeVerdict(passed=True, score=1.0)
            ModelGrader("judge", self.RUBRIC).grade("prose", _case())

        self.assertIs(ask.call_args.kwargs["allow_fallback"], False)


class PairwiseGraderTests(TestCase):
    CRITERION = "Which reads more like trustworthy journalism?"

    def _grader(self, reference="the baseline article"):
        return PairwiseGrader("pairwise", self.CRITERION, reference=reference)

    def test_no_reference_is_undecided_not_a_failure(self):
        """The first run, or a new case. Reporting it as a regression would
        make every new case look like damage."""
        grade = self._grader(reference="").grade("new article", _case())

        self.assertIsNone(grade.score)
        self.assertIn("no reference", grade.detail)

    def test_winning_scores_one(self):
        with patch("random.random", return_value=0.9):  # not swapped: candidate is A
            with _judging(PairwiseVerdict(winner="A", reasoning="clearer")):
                grade = self._grader().grade("new article", _case())

        self.assertEqual(grade.score, 1.0)
        self.assertTrue(grade.passed)
        self.assertEqual(grade.meta["winner"], "candidate")

    def test_losing_scores_zero(self):
        with patch("random.random", return_value=0.9):
            with _judging(PairwiseVerdict(winner="B", reasoning="the old one is better")):
                grade = self._grader().grade("new article", _case())

        self.assertEqual(grade.score, 0.0)
        self.assertFalse(grade.passed)
        self.assertEqual(grade.meta["winner"], "reference")

    def test_the_answer_is_mapped_back_when_positions_are_swapped(self):
        """Judges favour whatever they read first, so position is randomised.
        The mapping back is the part that would silently invert every score."""
        with patch("random.random", return_value=0.1):  # swapped: candidate is B
            with _judging(PairwiseVerdict(winner="B", reasoning="clearer")):
                grade = self._grader().grade("new article", _case())

        self.assertEqual(grade.score, 1.0)
        self.assertEqual(grade.meta["candidate_shown_as"], "B")

    def test_a_tie_is_not_a_regression(self):
        with _judging(PairwiseVerdict(winner="tie", reasoning="no real difference")):
            grade = self._grader().grade("new article", _case())

        self.assertEqual(grade.score, 0.5)
        self.assertTrue(grade.passed)

    def test_the_reference_can_be_looked_up_when_the_grader_runs(self):
        """A callable, so a case declared at import time can compare against a
        baseline captured long afterwards."""
        seen = {}

        def lookup(case):
            seen["case"] = case.name
            return "the baseline"

        with _judging(PairwiseVerdict(winner="tie")):
            PairwiseGrader("p", self.CRITERION, reference=lookup).grade(
                "x", _case(name="writer.prose")
            )

        self.assertEqual(seen["case"], "writer.prose")


class RenderingTests(TestCase):
    def test_a_schema_object_becomes_its_fields(self):
        rendered = render_for_judging(JudgeVerdict(passed=True, score=0.5,
                                                   reasoning="because"))
        self.assertIn("reasoning", rendered)
        self.assertIn("because", rendered)

    def test_empty_fields_are_left_out(self):
        """A judge reading twenty empty headings grades the formatting."""
        rendered = render_for_judging(JudgeVerdict(reasoning=""))
        self.assertNotIn("## reasoning", rendered)

    def test_long_output_is_capped(self):
        """A judge handed thirty thousand characters grades the beginning and
        skims the rest, which shows up as quality tracking length."""
        rendered = render_for_judging("x" * 50_000, limit=100)
        self.assertEqual(len(rendered), 100)

    def test_none_renders_empty(self):
        self.assertEqual(render_for_judging(None), "")


class LiveModeTests(TestCase):
    def test_a_case_without_a_stub_is_live(self):
        self.assertTrue(_case().is_live)

    def test_a_case_with_a_stub_is_not(self):
        self.assertFalse(_case(model_response={"x": 1}).is_live)

    def test_live_cases_are_skipped_by_default(self):
        """A suite that bills on every run is a suite people stop running, and
        a suite nobody runs measures nothing."""
        runner = EvalRunner()
        with patch("ai_workflows.harness.evals.runner.load_cases") as load:
            load.return_value = _registry_of(
                _case("live.one"),
                _case("stubbed.one", model_response={"x": 1},
                      graders=[DeterministicGrader("g", lambda o, c: True)]),
            )
            run = runner.run()

        self.assertEqual(
            list(EvalResult.objects.filter(run=run).values_list("case", flat=True)),
            ["stubbed.one"],
        )

    def test_live_cases_run_when_asked(self):
        runner = EvalRunner(live=True)
        with patch("ai_workflows.harness.evals.runner.load_cases") as load:
            load.return_value = _registry_of(
                _case("live.one", graders=[DeterministicGrader("g", lambda o, c: True)]),
            )
            run = runner.run()

        self.assertEqual(EvalResult.objects.filter(run=run, case="live.one").count(), 1)

    def test_selecting_only_live_cases_without_live_says_why(self):
        runner = EvalRunner()
        with patch("ai_workflows.harness.evals.runner.load_cases") as load:
            load.return_value = _registry_of(_case("live.one"))
            with self.assertRaises(ValueError) as caught:
                runner.run()

        self.assertIn("--live", str(caught.exception))


class BaselineOutputTests(TestCase):
    def setUp(self):
        self.case = _case("writer.prose")

    def test_nothing_recorded_yet_returns_empty(self):
        self.assertEqual(baseline_output(self.case), "")

    def test_the_baselines_output_comes_back(self):
        run = EvalRun.objects.create(is_baseline=True, status="complete")
        EvalResult.objects.create(
            run=run, agent="writer", case="writer.prose", grader="g",
            score=1.0, output={"rendered": "the approved article"},
        )
        self.assertEqual(baseline_output(self.case), "the approved article")

    def test_a_non_baseline_run_is_not_used_as_the_reference(self):
        """Comparing against whatever ran last would drift, one small
        acceptable loss at a time, until the suite measured against something
        nobody ever approved."""
        run = EvalRun.objects.create(is_baseline=False, status="complete")
        EvalResult.objects.create(
            run=run, agent="writer", case="writer.prose", grader="g",
            score=1.0, output={"rendered": "some later article"},
        )
        self.assertEqual(baseline_output(self.case), "")

    def test_an_output_is_stored_for_every_case_that_ran(self):
        runner = EvalRunner(live=True)
        with patch("ai_workflows.harness.evals.runner.load_cases") as load:
            load.return_value = _registry_of(
                _case("c", run=lambda f: "what the agent said",
                      graders=[DeterministicGrader("g", lambda o, c: True)]),
            )
            run = runner.run()

        stored = EvalResult.objects.get(run=run).output
        self.assertEqual(stored["rendered"], "what the agent said")


def _registry_of(*cases):
    from ai_workflows.harness.evals.cases import CaseRegistry

    registry = CaseRegistry()
    for case in cases:
        registry.register(case)
    return registry


class SuiteShapeTests(TestCase):
    """The suite as declared, rather than the machinery."""

    def setUp(self):
        from ai_workflows.harness.evals.cases import load_cases

        self.registry = load_cases()

    def test_the_writer_is_measured_at_all(self):
        """It had no eval until now, and it is the agent that fabricated."""
        self.assertTrue(self.registry.for_agent("writer"))

    def test_the_fabrication_case_is_live(self):
        """No stub will invent a statistic on the agent's behalf, so a stubbed
        version of that case would measure nothing."""
        case = next(c for c in self.registry.all()
                    if c.name == "writer.does_not_invent_statistics")
        self.assertTrue(case.is_live)

    def test_the_abstention_case_is_stubbed(self):
        """That one is about what the agent does with a refusal, not about
        whether the model issues one."""
        case = next(c for c in self.registry.all()
                    if c.name == "writer.abstains_on_an_empty_report")
        self.assertFalse(case.is_live)

    def test_every_case_has_at_least_one_grader(self):
        for case in self.registry.all():
            with self.subTest(case=case.name):
                self.assertTrue(case.graders, f"{case.name} is never graded")

    def test_every_case_explains_itself(self):
        """A case whose reason is not written down gets deleted by whoever
        breaks it next."""
        for case in self.registry.all():
            with self.subTest(case=case.name):
                self.assertTrue(len(case.description) > 40)


class SuppressionTests(TestCase):
    """An eval suite must not page the on-call.

    The live run that exposed this hit a Gemini quota limit, marked the real
    writer as failing, and would have emailed everyone holding `receive_alerts`
    -- an outage report generated by a test harness, about an agent nobody was
    using at the time.
    """

    def setUp(self):
        from django.contrib.auth.models import Permission, User

        from ai_workflows.harness.alerts import ALERT_CAPABILITY

        user = User.objects.create_user("ops", email="ops@example.com", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename=ALERT_CAPABILITY))

    def test_a_failure_inside_the_block_is_neither_recorded_nor_sent(self):
        from django.core import mail

        from ai_workflows.harness.alerts import record_failure, suppressed
        from ai_workflows.models import AgentHealth

        with suppressed("a test"):
            self.assertFalse(record_failure("writer", ModelUnavailable("no key")))

        self.assertEqual(mail.outbox, [])
        self.assertFalse(AgentHealth.objects.filter(agent="writer").exists())

    def test_recovery_is_suppressed_too(self):
        """Otherwise an eval run would announce a recovery from an outage that
        never happened."""
        from django.core import mail

        from ai_workflows.harness.alerts import record_failure, record_success, suppressed

        record_failure("writer", ModelUnavailable("a real outage"))
        mail.outbox.clear()

        with suppressed("a test"):
            self.assertFalse(record_success("writer"))

        self.assertEqual(mail.outbox, [])

    def test_alerting_resumes_afterwards(self):
        """Narrow, and restored. A suppression that leaked would silence the
        alerting for everything that ran next."""
        from django.core import mail

        from ai_workflows.harness.alerts import record_failure, suppressed

        with suppressed("a test"):
            record_failure("writer", ModelUnavailable("no key"))

        self.assertTrue(record_failure("writer", ModelUnavailable("no key")))
        self.assertEqual(len(mail.outbox), 1)

    def test_nesting_restores_the_outer_state(self):
        from ai_workflows.harness.alerts import is_suppressed, suppressed

        with suppressed():
            with suppressed():
                self.assertTrue(is_suppressed())
            self.assertTrue(is_suppressed())
        self.assertFalse(is_suppressed())

    def test_an_eval_run_leaves_agent_health_alone(self):
        from ai_workflows.harness.errors import ToolFailed
        from ai_workflows.models import AgentHealth

        def explode(fixture):
            from ai_workflows.harness.alerts import record_failure

            record_failure("writer", ToolFailed("quota exceeded"))
            raise ToolFailed("quota exceeded")

        runner = EvalRunner(live=True)
        with patch("ai_workflows.harness.evals.runner.load_cases") as load:
            load.return_value = _registry_of(_case("live.one", run=explode))
            run = runner.run()

        self.assertFalse(AgentHealth.objects.filter(agent="writer").exists())
        # The failure is still recorded where it belongs: on the eval result.
        self.assertEqual(
            EvalResult.objects.get(run=run).grader, "(raised)"
        )


class HonestReportingTests(TestCase):
    """A run where cases could not execute must not report success.

    The live run reported `overall: 1.00 (9 checks)` and exited zero while four
    of the nine had raised on a quota limit -- an eval suite lying about the
    one thing it exists to tell the truth about.
    """

    def _run_command(self, **options):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        try:
            call_command("run_evals", stdout=out, stderr=StringIO(), **options)
            return out.getvalue(), None
        except Exception as exc:  # noqa: BLE001 - the failure is the assertion
            return out.getvalue(), exc

    def _with_cases(self, *cases):
        return patch("ai_workflows.harness.evals.runner.load_cases",
                     return_value=_registry_of(*cases))

    def test_a_run_with_unmeasured_cases_fails_the_command(self):
        from django.core.management.base import CommandError

        def explode(fixture):
            raise RuntimeError("quota exceeded")

        with self._with_cases(
            _case("ok.one", model_response={"x": 1},
                  graders=[DeterministicGrader("g", lambda o, c: True)]),
            _case("broken.one", model_response={"x": 1}, run=explode),
        ):
            output, error = self._run_command()

        self.assertIsInstance(error, CommandError)
        self.assertIn("could not be measured", str(error))

    def test_the_count_is_of_what_was_graded(self):
        def explode(fixture):
            raise RuntimeError("quota exceeded")

        with self._with_cases(
            _case("ok.one", model_response={"x": 1},
                  graders=[DeterministicGrader("g", lambda o, c: True)]),
            _case("broken.one", model_response={"x": 1}, run=explode),
        ):
            output, _ = self._run_command()

        self.assertIn("1 of 2 checks graded", output)

    def test_a_clean_run_says_so_plainly(self):
        with self._with_cases(
            _case("ok.one", model_response={"x": 1},
                  graders=[DeterministicGrader("g", lambda o, c: True)]),
        ):
            output, error = self._run_command()

        self.assertIsNone(error)
        self.assertIn("1 of 1 checks graded", output)
        self.assertNotIn("could not be measured", output)

    def test_a_failing_check_still_fails_the_command(self):
        from django.core.management.base import CommandError

        with self._with_cases(
            _case("bad.one", model_response={"x": 1},
                  graders=[DeterministicGrader("g", lambda o, c: False)]),
        ):
            _, error = self._run_command()

        self.assertIsInstance(error, CommandError)
        self.assertIn("failed", str(error))
