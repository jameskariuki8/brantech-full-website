"""Eval cases: the held-out inputs, and what each one is checked for.

A case knows how to set up its own fixture, how to run the agent under test,
and which graders apply. Registering it is what puts it in the suite.

Cases live in code rather than a fixture file because setting one up means
building related model rows -- a dossier needs a topic -- and a JSON fixture
that has to be reassembled into objects is harder to read than the objects.
"""
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class EvalCase:
    """One held-out input for one agent.

    `setup` builds whatever the agent needs and returns it; `run` invokes the
    agent on that and returns its output. They are separate so a case can be
    set up once and run several times -- several samples per case is how the
    spread of a non-deterministic agent gets measured, rather than one sample
    being reported as if it were the answer.
    """

    name: str
    agent: str
    setup: Callable[[], Any]
    run: Callable[[Any], Any]
    graders: list = field(default_factory=list)
    description: str = ""

    # What the stubbed model should say for this case. A case that pins
    # behaviour -- "reject a dossier carrying a planted false claim" -- has to
    # control the model's answer, or it is measuring the weather.
    model_response: dict | None = None

    @property
    def is_live(self) -> bool:
        """Does this case need a real model call?

        The two kinds measure different things and neither replaces the other.
        A *stubbed* case asks what the agent does with a given model response:
        given a reported contradiction, does the gate refuse? A *live* case
        asks what the model actually produces, which is the only way to catch
        the writer inventing a statistic -- no stub will invent one for it.

        Live cases cost money and need a working provider, so they are opt-in.
        """
        return self.model_response is None


class CaseRegistry:
    """Every registered case, addressable by agent."""

    def __init__(self):
        self._cases: list[EvalCase] = []

    def register(self, case: EvalCase) -> EvalCase:
        if any(c.name == case.name for c in self._cases):
            raise ValueError(f"duplicate eval case: {case.name}")
        self._cases.append(case)
        return case

    def all(self) -> list[EvalCase]:
        return list(self._cases)

    def for_agent(self, agent: str) -> list[EvalCase]:
        return [c for c in self._cases if c.agent == agent]

    def agents(self) -> list[str]:
        return sorted({c.agent for c in self._cases})

    def __len__(self):
        return len(self._cases)


registry = CaseRegistry()


def load_cases():
    """Import the case modules for their registration side effects.

    Called by the runner rather than at import of this module, so that
    importing the registry never drags in Django models.
    """
    from ai_workflows.harness.evals import suites  # noqa: F401

    return registry
