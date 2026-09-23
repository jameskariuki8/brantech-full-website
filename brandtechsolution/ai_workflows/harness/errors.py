"""The failure taxonomy.

Every agent in this codebase currently invents its own failure behaviour:
a try/except that sets `self.model = None`, then a canned draft returned as
though the model had written it. A deployment with a rotated API key does not
fail -- it publishes invented statistics.

Nothing here is caught and converted into content. A stage that cannot do its
job raises, the run is marked failed, and somebody is told. The one place
these are caught is the *edge* -- a chat view rendering "I can't reach my
tools right now" -- never inside an agent.
"""


class AgentError(Exception):
    """Base for everything the harness raises."""

    def __init__(self, message, *, agent=None, provider=None, model=None):
        super().__init__(message)
        self.agent = agent
        self.provider = provider
        self.model = model

    def __str__(self):
        base = super().__str__()
        where = ", ".join(
            f"{label}={value}"
            for label, value in (
                ("agent", self.agent), ("provider", self.provider), ("model", self.model)
            )
            if value
        )
        return f"{base} ({where})" if where else base


class ModelUnavailable(AgentError):
    """The provider could not be reached, built, or authenticated.

    Raised rather than returning None. `self.model = None` is what made silent
    degradation representable in the first place; a type that cannot hold
    "absent" cannot be ignored.
    """


class AgentOutputInvalid(AgentError):
    """The model answered, but not in the shape the caller requires.

    Raised only after the contract's retry has also failed, so this means the
    model was told what was wrong with its first attempt and still did not
    comply.
    """

    def __init__(self, message, *, raw=None, **kwargs):
        super().__init__(message, **kwargs)
        # The offending text, for the invocation record. Debugging a schema
        # failure without the response that caused it is guesswork.
        self.raw = raw


class ToolFailed(AgentError):
    """A tool bound to an agent raised."""

    def __init__(self, message, *, tool=None, **kwargs):
        super().__init__(message, **kwargs)
        self.tool = tool


class MemoryUnavailable(AgentError):
    """The memory store could not be read or written."""


class BudgetExceeded(AgentError):
    """The run hit its spend or token ceiling.

    A ceiling that reports after the fact is a report; one that stops the work
    is a ceiling. This is the second.
    """
