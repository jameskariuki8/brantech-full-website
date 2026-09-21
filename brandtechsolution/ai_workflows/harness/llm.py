"""Model access: the only file in the codebase that names a vendor.

Six agents currently build their own `ChatGoogleGenerativeAI`, differing only
in temperature, each wrapped in a try/except that sets `self.model = None`.
Changing the model, adding a retry, setting a timeout or capping tokens means
editing six files and hoping none was missed.

Roles rather than raw temperatures. The six values in use are really four
intentions, and naming the intention means a future model swap re-tunes in one
place instead of six -- 0.4 is not a fact about the writer, it is a guess about
Gemini that will be wrong for the next model.

Providers beyond Gemini land in step 3 with the catalogue. The seam is here so
that is an addition rather than a rewrite.
"""
import logging
from enum import Enum

from brandtechsolution.config import config

from ai_workflows.harness.errors import ModelUnavailable

logger = logging.getLogger(__name__)


class ModelRole(str, Enum):
    """What a call needs from a model, not how to get it."""

    PRECISE = "precise"            # verification, extraction: be literal
    ANALYTIC = "analytic"          # scoring, research: reason, do not embellish
    CREATIVE = "creative"          # drafting, social: write something readable
    CONVERSATIONAL = "conversational"  # the assistant


# Tuned to match what the agents use today, so adopting the harness is not
# also a silent change in behaviour: verifier 0.1, intelligence 0.2, research
# 0.3, writer and social 0.4.
ROLE_TEMPERATURE = {
    ModelRole.PRECISE: 0.1,
    ModelRole.ANALYTIC: 0.25,
    ModelRole.CREATIVE: 0.4,
    ModelRole.CONVERSATIONAL: 0.4,
}


class Provider(str, Enum):
    GEMINI = "gemini"


def _gemini(role, tools, **overrides):
    from langchain_google_genai import ChatGoogleGenerativeAI

    if not config.google_api_key:
        raise ModelUnavailable(
            "GOOGLE_API_KEY is not set", provider=Provider.GEMINI.value
        )

    kwargs = {
        "model": config.gemini_chat_model,
        "google_api_key": config.google_api_key,
        "temperature": ROLE_TEMPERATURE[role],
        "timeout": getattr(config, "llm_timeout", 60),
        # Retry transport failures here rather than in each agent. Content
        # failures are the contract's business, not the client's.
        "max_retries": 2,
    }
    kwargs.update(overrides)

    try:
        model = ChatGoogleGenerativeAI(**kwargs)
    except Exception as exc:  # noqa: BLE001 - re-raised as our own type
        raise ModelUnavailable(
            f"could not build the Gemini client: {exc}",
            provider=Provider.GEMINI.value,
            model=kwargs["model"],
        ) from exc

    return model.bind_tools(tools) if tools else model


_BUILDERS = {Provider.GEMINI: _gemini}


def get_model(role=ModelRole.ANALYTIC, *, tools=None, provider=None, agent=None, **overrides):
    """A configured chat model for `role`.

    Raises `ModelUnavailable` rather than returning None. That is the whole
    point of this function existing: `self.model = None` is what let a missing
    API key turn into published fabrications instead of a failed run, and a
    return type that cannot express "absent" cannot be quietly ignored.
    """
    role = ModelRole(role)
    provider = Provider(provider) if provider else Provider.GEMINI

    builder = _BUILDERS.get(provider)
    if builder is None:
        raise ModelUnavailable(f"no builder for provider {provider.value}", agent=agent)

    try:
        return builder(role, tools, **overrides)
    except ModelUnavailable as exc:
        exc.agent = exc.agent or agent
        raise


def get_embedder(*, provider=None, agent=None):
    """The embedding model.

    Resolved separately from `get_model` on purpose. Chat can fail over between
    providers mid-run without anyone noticing; embeddings cannot fail over at
    all, because a vector from another model is not merely differently sized --
    it is meaningless in the same space as the stored ones. A deployment can
    run one provider for chat while embeddings stay on another, and losing the
    embedding provider degrades memory whatever else is configured.
    """
    provider = Provider(provider) if provider else Provider.GEMINI

    if provider is not Provider.GEMINI:
        raise ModelUnavailable(
            f"no embedding support for {provider.value}", provider=provider.value, agent=agent
        )

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    if not config.google_api_key:
        raise ModelUnavailable(
            "GOOGLE_API_KEY is not set", provider=provider.value, agent=agent
        )

    try:
        return GoogleGenerativeAIEmbeddings(
            model=config.gemini_embedding_model,
            google_api_key=config.google_api_key,
        )
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable(
            f"could not build the embedding client: {exc}",
            provider=provider.value,
            model=config.gemini_embedding_model,
            agent=agent,
        ) from exc
