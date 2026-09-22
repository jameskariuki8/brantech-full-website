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
on iterations rather than tokens for the same reason the supervisor's is: real
spend accounting needs usage off the provider, and a plausible-looking
approximation of it would be worse than an honest iteration count.
"""
import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ai_workflows.harness.errors import AgentError, ToolFailed
from ai_workflows.harness.llm import ModelRole, get_model

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 4

# Tool output is untrusted text from somewhere else -- a fetched page, a stored
# document -- and the single largest thing in a context window if left alone.
MAX_RESULT_CHARS = 8_000


def gather(persona, brief, tools, *, role=ModelRole.ANALYTIC, agent=None,
           max_steps=DEFAULT_MAX_STEPS, allow_fallback=True):
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

    model = get_model(role, tools=tools, agent=agent, allow_fallback=allow_fallback)
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
        try:
            response = model.invoke(messages)
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolFailed(f"the gathering step failed: {exc}", agent=agent) from exc

        messages.append(response)
        calls = getattr(response, "tool_calls", None) or []

        if not calls:
            summary = _text_of(response)
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

            result = result[:MAX_RESULT_CHARS]
            transcript.append(f"[{name}({_brief_args(args)})]\n{result}")
            messages.append(ToolMessage(
                content=result, tool_call_id=call.get("id", name),
            ))
    else:
        logger.info(
            "[gather] %s hit the %d-step ceiling; using what it had", agent, max_steps,
        )

    return "\n\n".join(transcript)


def _text_of(response):
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = [
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        ]
        return "\n".join(p for p in parts if p).strip()
    return str(content or "").strip()


def _brief_args(args):
    """Arguments, short enough to read in a transcript."""
    return ", ".join(f"{k}={str(v)[:120]!r}" for k, v in sorted(args.items()))
