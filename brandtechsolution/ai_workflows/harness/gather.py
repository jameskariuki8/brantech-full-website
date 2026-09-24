"""Letting an agent look things up before it answers.

`contract.ask` is one call that returns a validated object. It cannot use
tools, and that is deliberate -- the same reasoning the contract module gives
for separating persona from format applies again here. A single call asked to
research a question *and* emit a schema does neither well: the tool loop wants
freedom to wander and the schema wants a single clean answer, and asking for
both produces a half-hearted search followed by a grudging object.

So the work is split. `gather` runs a bounded tool loop and returns what it
found as plain text; the caller then hands that text to `ask` as evidence. Two
calls, each doing one thing, and -- the part that matters for the verifier --
the evidence is *visible* between them. It can be logged, stored on the report,
and read by a human wondering why the agent decided what it did.

Bounded because a tool loop with no ceiling is an unbounded bill. The limit is
on iterations rather than tokens: an iteration is knowable before the call,
which is what a ceiling needs to be. What each iteration actually consumed is
now recorded as it happens -- see `harness/usage.py` -- so the two answer
different questions rather than one standing in for the other.
"""
import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ai_workflows.harness.context import truncate_tool_result
from ai_workflows.harness.contract import text_of
from ai_workflows.harness.errors import AgentError, ModelUnavailable, ToolFailed
from ai_workflows.harness.fetching import MAX_CHARS
from ai_workflows.harness.llm import ModelRole, iter_models
from ai_workflows.harness.retrying import BATCH, call_with_retries

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 4

# Tool output is untrusted text from somewhere else -- a fetched page, a stored
# document -- and the single largest thing in a context window if left alone.
#
# The fetcher's own cap, not a tighter one. At 8,000 this cut pages the fetcher
# had deliberately kept, and did it silently: the verifier read a Wikipedia
# page whose spec table sat past the cut, reported a correct processor claim as
# unsupported, and rejected a sound dossier on the confidence that cost it.
MAX_RESULT_CHARS = MAX_CHARS


def gather(persona, brief, tools, *, role=ModelRole.ANALYTIC, agent=None,
           max_steps=DEFAULT_MAX_STEPS, allow_fallback=True, policy=BATCH):
    """Let the model use `tools` to answer `brief`, and return what it found.

    Returns the evidence as text: each tool call and its result, followed by
    the model's own summary. An agent that used no tools returns just the
    summary, which is a legitimate outcome -- not every claim needs a source
    fetched to check it.

    Raises like anything else in the harness. A gathering step that failed has
    not produced thin evidence, it has produced none, and letting the caller
    proceed on an empty string would be the fallback pattern again in a new
    place.
    """
    if not tools:
        return ""

    invoke = _Failover(role, tools, agent=agent, allow_fallback=allow_fallback,
                       policy=policy)
    by_name = {tool.name: tool for tool in tools}

    messages = [
        SystemMessage(content=(
            f"{persona.render()}\n\n"
            "Before answering, use your tools to check what you can. Report "
            "what you found, including when a source did not say what was "
            "claimed. Say plainly when you could not verify something -- an "
            "unchecked claim reported as unchecked is useful; one reported as "
            "checked is not."
        )) if persona is not None else SystemMessage(content=(
            "Use your tools to gather evidence, then report what you found."
        )),
        HumanMessage(content=brief),
    ]

    transcript = []

    for step in range(max_steps):
        response = invoke(messages)

        messages.append(response)
        calls = getattr(response, "tool_calls", None) or []

        if not calls:
            summary = text_of(response)
            if summary:
                transcript.append(summary)
            break

        for call in calls:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            tool = by_name.get(name)

            if tool is None:
                # The model asked for something it was not given. Told, rather
                # than failed: it can pick a tool it does have.
                result = f"No tool named {name!r} is available to you."
                logger.info("[gather] %s asked for an unavailable tool %r", agent, name)
            else:
                try:
                    result = str(tool.invoke(args))
                except Exception as exc:  # noqa: BLE001
                    # A tool that raised is a fact about that lookup, not about
                    # the run. The agent should know and carry on.
                    logger.warning("[gather] %s raised: %s", name, exc)
                    result = f"That lookup failed: {exc}"

            result = truncate_tool_result(result, MAX_RESULT_CHARS)
            transcript.append(f"[{name}({_brief_args(args)})]\n{result}")
            messages.append(ToolMessage(
                content=result, tool_call_id=call.get("id", name),
            ))
    else:
        logger.info(
            "[gather] %s hit the %d-step ceiling; using what it had", agent, max_steps,
        )

    return "\n\n".join(transcript)


class _Failover:
    """Invokes the model, moving to the next provider when one cannot answer.

    `get_model` returns a client that built successfully, which says nothing
    about whether it will answer. A rate limit arrives at invoke time, and the
    live eval run that exposed this lost every writer case to one exhausted
    quota while four other providers sat unused -- the same defect `ask` had,
    surviving here because the fix was applied at one call site instead of to
    the pattern.

    A provider that failed is dropped for the rest of the loop rather than
    retried on the next step. A 429 or a revoked key does not clear itself in
    the second between two calls, so re-offering it would spend the step budget
    rediscovering the same outage. That bounds the whole loop at `max_steps`
    calls plus one wasted attempt per provider.
    """

    def __init__(self, role, tools, *, agent, allow_fallback, policy=BATCH):
        self._agent = agent
        self._allow_fallback = allow_fallback
        self._policy = policy
        self._candidates = iter_models(
            role, tools=tools, agent=agent, allow_fallback=allow_fallback,
        )
        self._current = None
        self._failures = []

    def __call__(self, messages):
        while True:
            provider, client = self._client()
            try:
                # Wait out a refusal that clears on its own before deciding
                # this provider cannot answer. On the free tier a five-per-
                # minute window is the normal working condition, not an
                # outage, and failing over on it would abandon a provider
                # that was about to say yes.
                response = call_with_retries(
                    lambda: client.invoke(messages),
                    policy=self._policy, label=provider.value, agent=self._agent,
                )
                self._account(provider, client, response)
                return response
            except AgentError:
                raise
            except Exception as exc:  # noqa: BLE001
                label = provider.value if provider is not None else "the model"
                if not self._allow_fallback:
                    # Pinned on purpose -- an eval comparing runs, say. Drifting
                    # to another provider would answer a different question.
                    raise ToolFailed(
                        f"the gathering step failed: {exc}", agent=self._agent,
                    ) from exc
                self._failures.append(f"{label}: {exc}")
                logger.warning(
                    "[gather] %s could not answer for %s, trying the next "
                    "provider: %s", label, self._agent, exc,
                )
                # Hand control back to the generator, which offers the next.
                self._current = None

    def _account(self, provider, client, response):
        """Record what this step consumed.

        Inside the loop rather than around it: a gathering step that fails on
        its fourth tool call still paid for the first three, and accounting
        only successful *steps* would under-report exactly the runs worth
        investigating.
        """
        from ai_workflows.harness import usage

        usage.record(
            response,
            provider=provider.value if provider is not None else "",
            model=getattr(client, "model", ""),
            agent=self._agent or "",
            role="gather",
        )

    def _client(self):
        if self._current is not None:
            return self._current

        try:
            self._current = next(self._candidates)
        except StopIteration:
            raise self._exhausted() from None
        except ModelUnavailable as exc:
            # The generator raises this once its own candidates are spent; its
            # message names the ones that would not build, ours the ones that
            # would not answer.
            self._failures.append(str(exc))
            raise self._exhausted() from exc

        return self._current

    def _exhausted(self):
        detail = "; ".join(self._failures) or "no provider is usable"
        return ToolFailed(
            f"the gathering step failed, and so did every fallback: {detail}",
            agent=self._agent,
        )


def _brief_args(args):
    """Arguments, short enough to read in a transcript."""
    return ", ".join(f"{k}={str(v)[:120]!r}" for k, v in sorted(args.items()))
