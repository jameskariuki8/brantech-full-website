"""The one orchestrator, and the table it routes by.

Every agent in this system was previously reached by importing its class and
calling a method named after it. `conduct_research`, `verify_dossier`,
`write_article`, `send_message` -- twelve entry points with nothing in common,
so there was no place to ask "what agents are there", "which one is failing",
or "what would handle this".

This is that place. It routes *between* agents and never inside one: the
newsroom's fixed twelve-stage sequence stays the newsroom's own business,
reached as a single agent like any other. That is the whole reason `Agent.run`
is the only entry point the contract defines.

Routing is a table, not a model call. The deterministic spine was a decision
made up front and it holds here: a supervisor that asks a language model which
agent to use adds a failure mode -- and a bill -- to something a dictionary
already answers correctly. The day a routing decision genuinely needs judgement,
it can be an agent that returns a route, dispatched through this same table.
"""
import logging

from ai_workflows.harness.base import AgentRequest, AgentRegistry, AgentResult
from ai_workflows.harness.errors import BudgetExceeded

logger = logging.getLogger(__name__)

registry = AgentRegistry()


# ============================================================
# Routes
# ============================================================
# task -> agent. Most entries look like a rename, and the indirection is the
# point: a caller asks for `verify` and which agent verifies is the
# supervisor's business, not the caller's. That is what makes replacing an
# agent a one-line change here rather than a search across the codebase.

ROUTES = {
    "chat": "assistant",

    # The whole newsroom, as one agent. Its internal sequence is fixed and
    # stays fixed; the supervisor dispatches to it and does not look inside.
    "newsroom": "newsroom",

    # The newsroom's stages, individually addressable -- for a re-run of one
    # stage, for the evals, and for a future supervisor that assembles its own
    # sequence rather than using the canned one.
    "score_trend": "trend_intelligence",
    "forecast": "trend_prediction",
    "research": "research",
    "verify": "fact_verifier",
    "draft": "writer",
    "syndicate": "social",
}


# A run that dispatches more than this has lost track of itself. It catches
# the failure a supervisor introduces -- an agent routing to an agent that
# routes back -- which without a counter is an unbounded bill discovered at
# the end of the month.
DEFAULT_MAX_DISPATCHES = 50

# The other half of that, and the half that was missing. A dispatch count
# bounds how many *agents* run, which says nothing about what they spend: one
# agent making forty long calls inside a single dispatch is one dispatch.
# `harness/usage.py` records what each call consumed, and this is where the
# number is finally read.
#
# Approximate on purpose. Most catalogue prices are borrowed from OpenRouter
# rather than published by the provider that bills, and a call to an unpriced
# model cannot be counted at all -- so this is a runaway stop, not an
# accountant, and `Ledger.complete` is how a caller finds out which it got.


def _default_spend_ceiling():
    """Read at call time, not at import, so a test can override the setting."""
    from brandtechsolution.config import config

    return getattr(config, "agent_run_spend_ceiling_usd", 0.0) or 0.0


def load_agents(target=registry):
    """Import the agent modules for their registration side effects.

    Lazy, and called by the supervisor rather than at module import, because
    every agent module pulls in Django models -- importing the registry should
    not require the app registry to be ready.
    """
    if len(target):
        return target

    from ai_workflows.service import ChatAssistant
    from editorial.newsroom import NewsroomAgent
    from editorial.services.social import MultiPlatformContentAgent
    from editorial.services.writer import AIWriterAgent
    from research.services.fact_verifier import FactVerificationAgent
    from research.services.investigator import ResearchAgent
    from trends.services.intelligence import TrendIntelligenceAgent
    from trends.services.prediction import TrendPredictionAgent

    for agent_class in (
        TrendIntelligenceAgent, TrendPredictionAgent, ResearchAgent,
        FactVerificationAgent, AIWriterAgent, MultiPlatformContentAgent,
        NewsroomAgent,
    ):
        target.register(agent_class())

    # Built per call: a shared assistant would answer in whichever conversation
    # reached it last.
    target.register_factory(
        "assistant",
        lambda thread_id, user_id=None, **kw: ChatAssistant(
            thread_id=thread_id, user_id=user_id, **kw
        ),
    )

    return target


class Supervisor:
    """Routes a task to the agent that handles it.

    `max_dispatches` is per supervisor, so one instance is one run. Sharing an
    instance across runs would share the counter, and the ceiling would trip on
    whichever run happened to be unlucky.
    """

    def __init__(self, registry=registry, max_dispatches=DEFAULT_MAX_DISPATCHES,
                 run_id=None, max_spend_usd=None, label=""):
        from ai_workflows.harness.usage import Ledger

        self.registry = load_agents(registry)
        self.max_dispatches = max_dispatches
        self.run_id = run_id
        self.dispatches = 0
        self.trail = []

        # None means "use the configured ceiling"; 0 means "no ceiling", which
        # a caller has to ask for rather than get by leaving an argument out.
        self.max_spend_usd = (
            _default_spend_ceiling() if max_spend_usd is None else max_spend_usd
        )
        # Per supervisor, like the dispatch counter and for the same reason:
        # one instance is one run, and a shared ledger would trip whichever
        # run happened to be unlucky.
        self.ledger = Ledger(label=label, run_id=run_id)

    # ------------------------------------------------------------------
    # routing
    # ------------------------------------------------------------------

    def route(self, task):
        """The agent name for `task`.

        An unknown task raises rather than falling back to a default agent.
        Guessing would mean a typo in a task name silently reaching whichever
        agent happened to be the default, and its answer would look exactly
        like a correct one.
        """
        try:
            return ROUTES[task]
        except KeyError:
            known = ", ".join(sorted(ROUTES))
            raise KeyError(f"no route for task {task!r} (known: {known})") from None

    def agent_for(self, task, **kwargs):
        return self.registry.get(self.route(task), **kwargs)

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    def dispatch(self, task, payload=None, *, thread_id="", user_id=None,
                 metadata=None, **build):
        """Run the agent that handles `task`, and return its result.

        Goes through `Agent.execute`, so health is recorded and step 5's
        alerting fires on a failure. Abstentions come back on the result rather
        than as an exception: an agent declining is an answer, and the caller
        is the one that knows what to do about it.
        """
        self._charge(task)

        agent = self.agent_for(task, **build)
        request = AgentRequest(
            payload=payload or {},
            thread_id=thread_id,
            run_id=self.run_id,
            user_id=user_id,
            metadata=metadata or {},
        )

        logger.info("[supervisor] %s -> %s", task, agent.name)

        # Every model call made anywhere under this agent lands in this run's
        # ledger. A context variable rather than a `run_id` threaded through
        # `execute` -> `ask` -> `_ask_one`: four layers of parameter that exist
        # only for bookkeeping, where each new call site is a chance to forget
        # it and under-report.
        from ai_workflows.harness.usage import accounting

        with accounting(self.ledger):
            result = agent.execute(request)

        self.trail.append((task, agent.name, result.abstained))
        if result.abstained:
            logger.info(
                "[supervisor] %s declined: %s", agent.name,
                result.notes or "no reason given",
            )
        return result

    def _charge(self, task):
        """Refuse a dispatch this run cannot afford.

        Checked before dispatching rather than after, so a run stops between
        agents rather than abandoning one mid-call -- an agent killed partway
        through has still been paid for and has produced nothing.
        """
        if self.dispatches >= self.max_dispatches:
            raise BudgetExceeded(
                f"this run has dispatched {self.dispatches} times "
                f"(ceiling {self.max_dispatches}); refusing {task!r}"
            )

        if self.max_spend_usd and self.ledger.spend_usd >= self.max_spend_usd:
            unknown = (
                "" if self.ledger.complete
                else f", plus {self.ledger.unpriced_calls} call(s) at unknown prices"
            )
            raise BudgetExceeded(
                f"this run has spent ${self.ledger.spend_usd:.4f} of its "
                f"${self.max_spend_usd:.2f} ceiling{unknown}; refusing {task!r}"
            )

        self.dispatches += 1

    # ------------------------------------------------------------------
    # visibility
    # ------------------------------------------------------------------

    def spend(self):
        """What this run has cost so far.

        Returns the ledger rather than a float, because the float on its own
        is not answerable: `complete` says whether it is the whole bill or
        only the priced part of it.
        """
        return self.ledger

    def agents(self):
        """Every agent this supervisor can reach."""
        return self.registry.names()

    def status(self):
        """What each agent's health looks like right now.

        The question step 5 made answerable and nothing yet asked. Agents with
        no health row have never run and are reported as `unknown` rather than
        as healthy -- "we have never heard from it" and "it is fine" are
        different states, and conflating them is how a Beat task that stopped
        being scheduled goes unnoticed.
        """
        from ai_workflows.models import AgentHealth

        rows = {h.agent: h for h in AgentHealth.objects.all()}
        report = {}

        for name in self.agents():
            health = rows.get(name)
            if health is None:
                report[name] = {"status": "unknown", "error_class": "",
                                "failing_since": None, "suppressed": 0}
                continue

            report[name] = {
                "status": health.status,
                "error_class": health.error_class,
                "failing_since": health.failing_since,
                "suppressed": health.suppressed_since_alert,
            }
        return report
