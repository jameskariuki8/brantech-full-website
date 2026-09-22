"""prompt -> validated object. The only parser in the codebase.

Six agents currently ask for JSON in prose -- "Return ONLY raw JSON" -- then
strip an optional ``` fence with string operations, `json.loads` it, catch
everything, and return a canned dict. Six copies of the same dance, each with
its own fallback.

Two changes here beyond de-duplication.

**Native structure, not a request.** Every provider offers a mode that
constrains the output shape. Prompt-instructed JSON is a request the model may
decline; a native schema is structural. The fence-strip survives only as the
fallback for a model that lacks the feature.

**Abstention is legal.** A model handed a mandatory field and no way to say "I
could not determine this" will fill it. That is not a quirk -- it is where
*"Representative enterprise deployments demonstrate a 40% improvement in
performance"* came from. Every response model here carries a status, and
callers are expected to route on it.
"""
import json
import logging
import re
from enum import Enum

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError

from ai_workflows.harness.errors import AgentOutputInvalid, ModelUnavailable
from ai_workflows.harness.llm import ModelRole, iter_models as get_models
from ai_workflows.harness.retrying import BATCH, call_with_retries

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class OutputStatus(str, Enum):
    OK = "ok"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REFUSED = "refused"


class AgentOutput(BaseModel):
    """Base for every agent response schema.

    Subclasses add their own fields. They inherit the ability to decline,
    which is the point: a verifier that cannot verify something must be able
    to say so in a way the caller respects, rather than inventing a confidence
    score to fill the column.
    """

    status: OutputStatus = OutputStatus.OK
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str = ""

    @property
    def usable(self) -> bool:
        return self.status is OutputStatus.OK

    @property
    def abstained(self) -> bool:
        return self.status is not OutputStatus.OK


def strip_fence(text: str) -> str:
    """Remove a ``` fence if the model wrapped its JSON in one.

    One implementation, replacing six. Kept for the fallback path and for
    models without a native structured mode.
    """
    if not text:
        return ""
    match = _FENCE.match(text)
    return match.group(1) if match else text.strip()


def text_of(response):
    """The text of a model response, whatever shape it arrived in.

    Newer Gemini models return `content` as a list of typed blocks rather than
    a string -- `[{"type": "text", "text": "ok", "extras": {...}}]`. Code that
    assumed a string got a list, `strip_fence` raised a TypeError on it, and
    the broad catch below reported that as the provider being unavailable: an
    alert sending an operator to look for an outage that never happened, over
    a response that arrived perfectly well.

    One implementation, used by both `contract` and `gather`, because two
    copies is how the second one ends up not learning about the third shape.
    """
    content = getattr(response, "content", response)

    if isinstance(content, list):
        parts = [
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        ]
        return "\n".join(part for part in parts if part).strip()

    return str(content or "").strip()


def parse_json(text, schema):
    """Parse and validate, raising with the offending text attached."""
    cleaned = strip_fence(text)
    try:
        payload = json.loads(cleaned, strict=False)
    except ValueError as exc:
        raise AgentOutputInvalid(f"response was not JSON: {exc}", raw=text) from exc

    if not isinstance(payload, dict):
        raise AgentOutputInvalid(
            f"expected a JSON object, got {type(payload).__name__}", raw=text
        )

    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise AgentOutputInvalid(f"response did not match {schema.__name__}: {exc}",
                                 raw=text) from exc


def _structured(model, schema):
    """Bind the schema natively, or return None if unsupported.

    Preferred over prompting because it is structural rather than requested,
    and because it stops the persona and the format fighting: a single call
    asked to be an award-winning journalist *and* a JSON emitter does neither
    well.
    """
    binder = getattr(model, "with_structured_output", None)
    if binder is None:
        return None
    try:
        return binder(schema)
    except Exception as exc:  # noqa: BLE001 - fall back, do not fail
        logger.debug("[contract] native structured output unavailable: %s", exc)
        return None


def ask(persona, prompt, schema, *, role=ModelRole.ANALYTIC, model=None,
        retries=1, agent=None, context=None, allow_fallback=True, provider=None,
        policy=BATCH):
    """Ask the model for `schema`, and return it validated.

    Two different failures, handled two different ways.

    A **shape** failure is the model's answer being wrong, so it is asked again
    with the validation error appended -- told what was wrong rather than simply
    re-rolled. Same model: another provider is no more likely to satisfy a
    schema the first one misread.

    A **call** failure is the provider not answering at all: a timeout, a
    revoked key, a quota spent for the day. Retrying the same model is
    pointless and the next provider is the whole reason there is a preference
    order. The exception is a refusal that clears on its own -- a per-minute
    rate limit -- which `policy` waits out before any of this applies, because
    failing over from a provider that said "ask me in a minute" wastes it. `allow_fallback`
    is what decides whether that is allowed, so a verifier being compared
    across runs stays on one model and fails instead.

    After the retries are spent this raises. It never returns a canned object:
    a fabricated answer that looks like a real one is worse than a failure,
    which is the lesson the fallback drafts taught.
    """
    base_messages = list(context.messages) if context is not None else []
    if persona is not None and not base_messages:
        from langchain_core.messages import SystemMessage

        base_messages.append(SystemMessage(content=persona.render()))
    base_messages.append(HumanMessage(content=prompt))

    if model is not None:
        return _ask_one(model, base_messages, schema, retries=retries, agent=agent,
                        policy=policy)

    last_error = None
    for candidate_provider, client in get_models(
        role, agent=agent, allow_fallback=allow_fallback, provider=provider,
    ):
        try:
            return _ask_one(client, list(base_messages), schema,
                            retries=retries, agent=agent, policy=policy)
        except ModelUnavailable as exc:
            last_error = exc
            exc.provider = exc.provider or candidate_provider.value
            logger.warning(
                "[contract] %s could not answer for %s: %s",
                candidate_provider.value, agent or schema.__name__, exc,
            )
            # Back to the generator, which offers the next provider or stops.
            continue

    if last_error is not None:
        last_error.agent = last_error.agent or agent
        raise last_error

    raise ModelUnavailable("no provider answered", agent=agent)


def _ask_one(model, messages, schema, *, retries, agent, policy=BATCH):
    """One model, with the shape-failure retry.

    Two retries live here and they are not the same thing. This one answers a
    model that replied badly. The one inside `call` answers a provider that
    declined to reply *yet* -- a per-minute rate limit -- and waits it out
    rather than spending a shape retry on it or failing over to a provider
    that has no better chance.
    """
    structured = _structured(model, schema)
    attempt, last_error = 0, None

    def call(invoke):
        return call_with_retries(
            invoke, policy=policy, label=getattr(model, "model", ""), agent=agent,
        )

    while attempt <= retries:
        try:
            if structured is not None:
                result = call(lambda: structured.invoke(messages))
                # A native binding returns the model already; a loose one may
                # still hand back text.
                if isinstance(result, schema):
                    return result
                return parse_json(text_of(result), schema)

            response = call(lambda: model.invoke(messages))
            return parse_json(text_of(response), schema)

        except AgentOutputInvalid as exc:
            last_error = exc
            attempt += 1
            if attempt > retries:
                break
            logger.info(
                "[contract] %s returned an invalid shape, retrying with the error",
                agent or schema.__name__,
            )
            messages.append(HumanMessage(content=(
                f"That response was rejected: {exc}. "
                f"Reply again, matching the required schema exactly."
            )))
            # A retry of a *native* binding that produced something invalid is
            # unlikely to do better on the same path; drop to plain parsing so
            # the correction is actually read.
            structured = None

        except ModelUnavailable:
            raise

        except Exception as exc:  # noqa: BLE001
            # The call did not complete. That is the provider failing, not the
            # model answering badly -- it used to be reported as an invalid
            # shape, which sent anyone reading the alert to look for a
            # malformed response that did not exist, and stopped the caller
            # from knowing another provider was worth trying.
            raise ModelUnavailable(
                f"the call failed: {exc}", agent=agent,
            ) from exc

    last_error.agent = last_error.agent or agent
    raise last_error


def require(output, *fields, agent=""):
    """Assert that an `ok` answer actually filled the fields that matter.

    Every content field on these schemas carries a default, because that is
    what makes abstention expressible: a model handed a mandatory field and no
    way to decline will fill it, which is where the invented statistics came
    from. The cost of that choice is that `{}` now validates cleanly.

    This closes it from the other side. The schema says what *may* be absent;
    the agent says what must be present when it claims to have succeeded. An
    empty article that passed validation is a failure, and saying so here is
    the difference between a loud one and a blank page in the review queue.
    """
    missing = [name for name in fields if not getattr(output, name, None)]
    if missing:
        raise AgentOutputInvalid(
            f"status was {output.status.value} but {', '.join(missing)} came back empty",
            agent=agent,
        )
    return output
