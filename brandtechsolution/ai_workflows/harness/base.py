"""The agent contract, and the registry that resolves a name to one.

`run` is the only entry point the orchestrator knows. Everything inside it is
the agent's own business -- which is what keeps the editorial pipeline's fixed
eleven-stage sequence legal under this design. The orchestrator routes between
*agents*; it does not decide what happens inside one.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ai_workflows.harness.llm import ModelRole

logger = logging.getLogger(__name__)


@dataclass
class AgentRequest:
    """What an agent is asked to do."""

    payload: dict = field(default_factory=dict)
    thread_id: str = ""
    run_id: int | None = None
    user_id: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """What it did.

    `output` carries the agent's schema object. `abstained` is surfaced here
    rather than left inside the output so a caller routing on it does not have
    to know the schema -- the orchestrator needs to stop a pipeline without
    understanding what a dossier is.
    """

    agent: str
    output: object = None
    abstained: bool = False
    notes: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def usable(self):
        return not self.abstained


class Agent(ABC):
    """One unit the orchestrator can dispatch to."""

    name: str = "agent"
    persona = None
    model_role: ModelRole = ModelRole.ANALYTIC
    tool_suite: str | None = None
    memory_scope: str = "default"

    # An agent whose output is compared across runs -- a verifier, a grader --
    # should not silently change model mid-comparison. This is read by the
    # provider layer in step 3.
    allow_fallback: bool = True

    @abstractmethod
    def run(self, request: AgentRequest) -> AgentResult:
        """Do the work.

        Raises rather than returning something plausible. Callers go through
        `execute` so the raise is also recorded.
        """

    def execute(self, request: AgentRequest) -> AgentResult:
        """`run`, with the agent's health recorded either side of it.

        Every caller should use this rather than `run`. Step 5 built the
        alerting before there was anything to alert about; this is the wire.
        Without it, removing the fallbacks would trade a bad draft for silence,
        which is not obviously the better failure.

        An *abstention* is not a failure and is not recorded as one -- an agent
        that declines because the evidence is thin is working correctly, and
        paging someone about it would teach them to ignore the alerts.
        """
        from ai_workflows.harness.alerts import record_failure, record_success
        from ai_workflows.harness.errors import AgentError

        try:
            result = self.run(request)
        except AgentError as exc:
            record_failure(
                self.name, exc,
                provider=exc.provider or "", model=exc.model or "",
                run_id=request.run_id,
            )
            raise

        record_success(self.name)
        return result

    def gather_evidence(self, brief, *, context=None, max_steps=None):
        """Look things up with this agent's tool suite, and return what it found.

        Empty string when the agent has no suite, so a caller can always fold
        the result into its prompt without branching. An agent with tools that
        found nothing is different from an agent with no tools, and both are
        different from a gathering step that *failed* -- which raises, because
        proceeding on an empty string would be the fallback pattern again.
        """
        from ai_workflows.harness.gather import DEFAULT_MAX_STEPS, gather
        from ai_workflows.harness.tools import ToolContext, register_builtin_tools, suite_for

        if not self.tool_suite:
            return ""

        register_builtin_tools()
        tools = suite_for(self.tool_suite, context or ToolContext())
        if not tools:
            return ""

        return gather(
            self.voiced_persona(), brief, tools,
            role=self.model_role, agent=self.name,
            max_steps=max_steps or DEFAULT_MAX_STEPS,
        )

    def voiced_persona(self):
        """This agent's persona, speaking in the stored brand voice.

        The voice is not declared on the persona because it is not this
        agent's to decide. `EditorialMemory.brand_voice` was read only by the
        writer while the chat assistant carried its own hardcoded copy, so the
        company had one brand voice and the codebase had two. `AgentProfile` is
        now the one, and this is how it reaches every agent.

        Note that `fingerprint` deliberately covers only the *declared*
        persona. Folding the stored voice in would make the digest a database
        read, and nothing uses the step cache yet; the day it does, editing the
        brand voice must invalidate it, and that belongs with that step.
        """
        if self.persona is None:
            return None

        from ai_workflows.models import AgentProfile

        return self.persona.with_voice(AgentProfile.load().brand_voice)

    def fingerprint(self) -> str:
        """Digest of this agent's version, for step cache keys.

        Persona and model role both feed it: changing either changes what the
        agent produces, so cached results from before the change must not be
        served after it.
        """
        import hashlib

        parts = [
            self.name,
            self.persona.fingerprint() if self.persona is not None else "",
            str(self.model_role),
            self.tool_suite or "",
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def __str__(self):
        return self.name


class AgentRegistry:
    """name -> agent, so the supervisor can route without importing each one.

    Two kinds, for the same reason `ToolRegistry` has two. Most agents are
    stateless and one instance serves every caller. The assistant is not: it is
    built around a `thread_id`, and a shared instance would answer in whichever
    conversation called it last -- a data leak rather than a design preference.
    """

    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._factories: dict[str, object] = {}

    def register(self, agent: Agent) -> Agent:
        self._guard(agent.name)
        self._agents[agent.name] = agent
        return agent

    def register_factory(self, name: str, factory):
        """Register an agent that must be built per call."""
        self._guard(name)
        self._factories[name] = factory
        return factory

    def _guard(self, name):
        if name in self._agents or name in self._factories:
            raise ValueError(f"an agent named {name!r} is already registered")

    def get(self, name: str, **kwargs) -> Agent:
        if name in self._agents:
            if kwargs:
                raise TypeError(
                    f"{name!r} is registered as a shared instance and takes no "
                    f"arguments; got {', '.join(sorted(kwargs))}"
                )
            return self._agents[name]

        factory = self._factories.get(name)
        if factory is None:
            known = ", ".join(self.names()) or "none"
            raise KeyError(f"no agent named {name!r} (registered: {known})") from None

        return factory(**kwargs)

    def names(self):
        return sorted({*self._agents, *self._factories})

    def __contains__(self, name):
        return name in self._agents or name in self._factories

    def __len__(self):
        return len(self._agents) + len(self._factories)


registry = AgentRegistry()
