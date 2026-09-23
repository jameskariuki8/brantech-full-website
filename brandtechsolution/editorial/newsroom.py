"""The newsroom as a single agent.

The supervisor routes between agents and never inside one. The editorial
pipeline's twelve stages are a fixed sequence that has to run in that order --
you cannot verify a dossier that has not been researched -- so it is not
something to route through. It is one agent whose `run` happens to take
minutes.

This is the shape `harness/base.py` describes when it says the pipeline's fixed
sequence stays legal under the design: `run` is the only entry point the
supervisor knows, and everything inside it is the agent's own business.

Deliberately thin. All the work is still in `EditorialPipelineOrchestrator`,
which is unchanged -- this is the seam that makes it reachable by name, not a
rewrite of it.
"""
import logging

from ai_workflows.harness.base import Agent, AgentRequest, AgentResult
from ai_workflows.harness.llm import ModelRole
from ai_workflows.harness.persona import Persona

logger = logging.getLogger(__name__)

# It has one, because every agent declares one, but it is never rendered into a
# prompt: this agent makes no model call of its own. Its subagents each carry
# their own, and stacking a thirteenth on top of theirs would only dilute them.
PERSONA = Persona(
    name="newsroom",
    role="the Teklora editorial pipeline: discovery, scoring, research, "
         "verification, drafting, and handoff to a human editor",
    directives=(
        "Run the stages in order and stop the topic at the first one that "
        "declines.",
    ),
    constraints=(
        "Never publish without a human approving the draft.",
    ),
)


class NewsroomAgent(Agent):
    """One full autonomous cycle, as a dispatchable unit."""

    name = "newsroom"
    persona = PERSONA
    model_role = ModelRole.ANALYTIC
    tool_suite = None

    def __init__(self, priority_threshold: float = 6.5):
        self.priority_threshold = priority_threshold

    def run(self, request: AgentRequest) -> AgentResult:
        """Run a cycle. `payload` takes limit, auto_publish and on_stage.

        A cycle that produced no articles is an abstention rather than a
        failure, and the two are genuinely different: nothing prioritised this
        week is an ordinary Tuesday, and paging somebody about it would teach
        them to ignore the alerts. An agent that *failed* inside the pipeline
        has already recorded its own health on the way past.
        """
        from editorial.orchestrator import EditorialPipelineOrchestrator

        payload = request.payload
        orchestrator = EditorialPipelineOrchestrator(
            priority_threshold=payload.get("priority_threshold", self.priority_threshold),
            # A re-run of a cycle that died partway reuses the stages that
            # already succeeded. `resume=False` forces every stage to run
            # again, which is what an eval wants: measuring an agent whose
            # answer came from cache measures the cache.
            resume=payload.get("resume", True),
        )

        articles = orchestrator.run_full_autonomous_cycle(
            limit=payload.get("limit", 1),
            auto_publish=payload.get("auto_publish", False),
            on_stage=payload.get("on_stage"),
        )

        return AgentResult(
            agent=self.name,
            output=articles,
            abstained=not articles,
            notes="" if articles else "the cycle produced no articles",
            metadata={"article_ids": [a.id for a in articles]},
        )
