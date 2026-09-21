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
        """Do the work."""

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
    """name -> agent, so the orchestrator can route without importing each one."""

    def __init__(self):
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> Agent:
        if agent.name in self._agents:
            raise ValueError(f"an agent named {agent.name!r} is already registered")
        self._agents[agent.name] = agent
        return agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError:
            known = ", ".join(sorted(self._agents)) or "none"
            raise KeyError(f"no agent named {name!r} (registered: {known})") from None

    def names(self):
        return sorted(self._agents)

    def __contains__(self, name):
        return name in self._agents

    def __len__(self):
        return len(self._agents)


registry = AgentRegistry()
