"""Step 8: the supervisor, the registry, and dispatch.

Twelve entry points named after the agent behind them became one. These tests
are about the routing table staying honest and the ceiling actually stopping
work -- the agents' own behaviour is covered where the agents are.
"""
from unittest.mock import patch

from django.test import TestCase

from ai_workflows.harness.base import Agent, AgentRegistry, AgentRequest, AgentResult
from ai_workflows.harness.errors import BudgetExceeded, ModelUnavailable
from ai_workflows.harness.supervisor import (
    DEFAULT_MAX_DISPATCHES,
    ROUTES,
    Supervisor,
    load_agents,
)
from ai_workflows.models import AgentHealth


class Echo(Agent):
    name = "echo"

    def __init__(self, marker="shared"):
        self.marker = marker

    def run(self, request):
        return AgentResult(agent=self.name, output=request.payload)


class Declines(Agent):
    name = "declines"

    def run(self, request):
        return AgentResult(agent=self.name, abstained=True, notes="not enough to go on")


class Breaks(Agent):
    name = "breaks"

    def run(self, request):
        raise ModelUnavailable("no key", provider="gemini")


class RegistryTests(TestCase):
    def setUp(self):
        self.registry = AgentRegistry()

    def test_a_shared_agent_resolves_to_the_same_instance(self):
        self.registry.register(Echo())
        self.assertIs(self.registry.get("echo"), self.registry.get("echo"))

    def test_a_factory_builds_a_fresh_agent_per_call(self):
        """The assistant is built around a thread_id.

        A shared instance would answer in whichever conversation reached it
        last, which is a data leak rather than a design preference.
        """
        self.registry.register_factory("echo", lambda marker: Echo(marker))

        first = self.registry.get("echo", marker="thread-a")
        second = self.registry.get("echo", marker="thread-b")

        self.assertIsNot(first, second)
        self.assertEqual(first.marker, "thread-a")

    def test_arguments_to_a_shared_agent_are_refused(self):
        """Ignoring them would hand back an agent configured for somebody else."""
        self.registry.register(Echo())
        with self.assertRaises(TypeError):
            self.registry.get("echo", marker="thread-a")

    def test_a_name_cannot_be_both_shared_and_built(self):
        self.registry.register(Echo())
        with self.assertRaises(ValueError):
            self.registry.register_factory("echo", lambda: Echo())

    def test_an_unknown_name_lists_what_is_registered(self):
        self.registry.register(Echo())
        with self.assertRaises(KeyError) as caught:
            self.registry.get("nope")
        self.assertIn("echo", str(caught.exception))

    def test_both_kinds_are_counted_and_listed(self):
        self.registry.register(Echo())
        self.registry.register_factory("built", lambda: Echo())
        self.assertEqual(len(self.registry), 2)
        self.assertEqual(self.registry.names(), ["built", "echo"])


def _supervisor(**kwargs):
    registry = AgentRegistry()
    for agent in (Echo(), Declines(), Breaks()):
        registry.register(agent)
    supervisor = Supervisor(registry=registry, **kwargs)
    return supervisor


class RoutingTests(TestCase):
    def test_every_route_names_a_registered_agent(self):
        """The drift guard that matters.

        A route pointing at an agent nobody registered fails at dispatch, in
        production, on whichever task happened to use it.
        """
        registry = load_agents(AgentRegistry())
        for task, agent in ROUTES.items():
            with self.subTest(task=task):
                self.assertIn(agent, registry, f"{task!r} routes to a missing agent")

    def test_every_registered_agent_is_reachable(self):
        """The reverse. An agent with no route is one the supervisor cannot
        dispatch to, which makes registering it decorative."""
        registry = load_agents(AgentRegistry())
        routed = set(ROUTES.values())
        for name in registry.names():
            with self.subTest(agent=name):
                self.assertIn(name, routed, f"{name!r} has no route")

    def test_an_unknown_task_raises_rather_than_defaulting(self):
        """Guessing would send a typo to whichever agent was the default, and
        its answer would look exactly like a correct one."""
        with patch.dict(ROUTES, {"echo": "echo"}, clear=False):
            with self.assertRaises(KeyError) as caught:
                _supervisor().route("eco")
        self.assertIn("echo", str(caught.exception))

    def test_the_route_is_an_indirection_not_a_rename(self):
        """A caller asks for a task; which agent serves it is not its business."""
        self.assertEqual(ROUTES["verify"], "fact_verifier")
        self.assertEqual(ROUTES["chat"], "assistant")


class DispatchTests(TestCase):
    def setUp(self):
        self.supervisor = _supervisor()
        self.patcher = patch.dict(
            ROUTES, {"echo": "echo", "decline": "declines", "break": "breaks"},
            clear=False,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_a_dispatch_returns_the_agent_result(self):
        result = self.supervisor.dispatch("echo", {"x": 1})
        self.assertEqual(result.output, {"x": 1})
        self.assertTrue(result.usable)

    def test_an_abstention_comes_back_as_a_result_not_an_exception(self):
        """An agent declining is an answer, and the caller is the one that
        knows what to do about it."""
        result = self.supervisor.dispatch("decline")
        self.assertTrue(result.abstained)
        self.assertEqual(result.notes, "not enough to go on")

    def test_a_failure_is_recorded_on_the_way_past(self):
        """Dispatch goes through execute, so step 5's alerting fires."""
        with self.assertRaises(ModelUnavailable):
            self.supervisor.dispatch("break")

        self.assertTrue(AgentHealth.objects.get(agent="breaks").is_failing)

    def test_the_run_id_reaches_the_agent(self):
        supervisor = _supervisor(run_id=7)
        with patch.object(Echo, "run", return_value=AgentResult(agent="echo")) as run:
            supervisor.dispatch("echo")
        self.assertEqual(run.call_args[0][0].run_id, 7)

    def test_the_trail_records_what_was_dispatched(self):
        self.supervisor.dispatch("echo")
        self.supervisor.dispatch("decline")
        self.assertEqual(
            self.supervisor.trail,
            [("echo", "echo", False), ("decline", "declines", True)],
        )


class BudgetTests(TestCase):
    def setUp(self):
        self.patcher = patch.dict(ROUTES, {"echo": "echo"}, clear=False)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_the_ceiling_stops_the_work_rather_than_reporting_it(self):
        """errors.py: a ceiling that reports after the fact is a report."""
        supervisor = _supervisor(max_dispatches=3)
        for _ in range(3):
            supervisor.dispatch("echo")

        with self.assertRaises(BudgetExceeded):
            supervisor.dispatch("echo")

    def test_the_ceiling_names_the_task_it_refused(self):
        supervisor = _supervisor(max_dispatches=1)
        supervisor.dispatch("echo")
        with self.assertRaises(BudgetExceeded) as caught:
            supervisor.dispatch("echo")
        self.assertIn("echo", str(caught.exception))

    def test_a_fresh_supervisor_is_a_fresh_budget(self):
        """One instance is one run. A shared counter would trip on whichever
        run happened to be unlucky."""
        first = _supervisor(max_dispatches=1)
        first.dispatch("echo")

        second = _supervisor(max_dispatches=1)
        self.assertTrue(second.dispatch("echo").usable)

    def test_the_default_ceiling_is_generous_enough_to_never_be_the_story(self):
        self.assertGreaterEqual(DEFAULT_MAX_DISPATCHES, len(ROUTES) * 2)


class StatusTests(TestCase):
    def test_an_agent_that_has_never_run_is_unknown_not_healthy(self):
        """"We have never heard from it" and "it is fine" are different states,
        and conflating them is how a Beat task that stopped being scheduled
        goes unnoticed."""
        report = _supervisor().status()
        self.assertEqual(report["echo"]["status"], "unknown")

    def test_a_failing_agent_is_reported_as_failing(self):
        with patch.dict(ROUTES, {"break": "breaks"}, clear=False):
            supervisor = _supervisor()
            with self.assertRaises(ModelUnavailable):
                supervisor.dispatch("break")

        report = supervisor.status()
        self.assertEqual(report["breaks"]["status"], AgentHealth.FAILING)
        self.assertEqual(report["breaks"]["error_class"], "ModelUnavailable")

    def test_every_agent_appears_whether_or_not_it_has_a_row(self):
        report = _supervisor().status()
        self.assertEqual(sorted(report), ["breaks", "declines", "echo"])


class RealAgentTests(TestCase):
    """The registry as the application actually builds it."""

    def test_the_assistant_is_built_per_thread(self):
        supervisor = Supervisor(registry=load_agents(AgentRegistry()))

        with patch("ai_workflows.service.iter_models"), \
                patch("ai_workflows.service.create_react_agent"):
            first = supervisor.agent_for("chat", thread_id="a")
            second = supervisor.agent_for("chat", thread_id="b")

        self.assertEqual(first.thread_id, "a")
        self.assertEqual(second.thread_id, "b")
        self.assertIsNot(first, second)

    def test_the_newsroom_is_one_agent_not_twelve(self):
        """The supervisor routes between agents and never inside one."""
        supervisor = Supervisor(registry=load_agents(AgentRegistry()))
        newsroom = supervisor.agent_for("newsroom")
        self.assertEqual(newsroom.name, "newsroom")

    def test_a_cycle_that_produced_nothing_abstains_rather_than_failing(self):
        """Nothing prioritised this week is an ordinary Tuesday."""
        from editorial.newsroom import NewsroomAgent

        with patch("editorial.orchestrator.EditorialPipelineOrchestrator"
                   ".run_full_autonomous_cycle", return_value=[]):
            result = NewsroomAgent().run(AgentRequest(payload={"limit": 1}))

        self.assertTrue(result.abstained)
        self.assertEqual(AgentHealth.objects.filter(agent="newsroom").count(), 0)

    def test_the_newsroom_reports_the_articles_it_made(self):
        from editorial.newsroom import NewsroomAgent

        article = type("A", (), {"id": 42})()
        with patch("editorial.orchestrator.EditorialPipelineOrchestrator"
                   ".run_full_autonomous_cycle", return_value=[article]):
            result = NewsroomAgent().run(AgentRequest(payload={}))

        self.assertFalse(result.abstained)
        self.assertEqual(result.metadata["article_ids"], [42])


class AgentsCommandTests(TestCase):
    """The operator-facing half: step 5's health, made reachable."""

    def _run(self, **options):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("agents", stdout=out, **options)
        return out.getvalue()

    def test_it_lists_every_agent_with_its_routes(self):
        output = self._run()
        self.assertIn("fact_verifier", output)
        self.assertIn("verify", output)
        self.assertIn("8 agents", output)

    def test_an_agent_that_has_never_run_is_not_reported_as_healthy(self):
        self.assertIn("never run", self._run())

    def test_a_failing_agent_shows_its_error_class(self):
        from ai_workflows.harness.alerts import record_failure

        record_failure("writer", ModelUnavailable("no key"))
        output = self._run()

        self.assertIn("FAILING", output)
        self.assertIn("ModelUnavailable", output)

    def test_the_failing_filter_says_so_when_nothing_is_wrong(self):
        self.assertIn("No agent is currently failing", self._run(failing=True))

    def test_the_failing_filter_shows_only_what_is_broken(self):
        from ai_workflows.harness.alerts import record_failure

        record_failure("writer", ModelUnavailable("no key"))
        output = self._run(failing=True)

        self.assertIn("writer", output)
        self.assertNotIn("fact_verifier", output)

    def test_suppressed_failures_are_surfaced(self):
        """Otherwise a storm of one error class looks like a single blip."""
        from ai_workflows.harness.alerts import record_failure

        for _ in range(4):
            record_failure("writer", ModelUnavailable("no key"))

        self.assertIn("suppressed", self._run(failing=True))

    def test_durations_read_as_durations(self):
        from datetime import timedelta

        from ai_workflows.management.commands.agents import _duration

        self.assertEqual(_duration(timedelta(seconds=30)), "30s")
        self.assertEqual(_duration(timedelta(minutes=5)), "5m")
        self.assertEqual(_duration(timedelta(hours=3)), "3h")
        self.assertEqual(_duration(timedelta(days=2)), "2d")
