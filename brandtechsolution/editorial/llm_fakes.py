"""A stand-in for Gemini, for tests of the editorial pipeline.

The newsroom tests used to construct the real agents and let them call the
live model. That made the suite depend on the developer's network and on the
API key's quota, and -- worse -- made it dishonest: every agent catches its
own exceptions and falls back to a canned draft, so with the network down the
tests passed without exercising a single line of the code they name. The same
tests then failed when the network was up and the model happened to return a
long title.

Patching here keeps the agents' real parsing, model wiring and database writes
under test while making the one thing they cannot control -- what the model
says -- deterministic.

Named llm_fakes rather than test_support so Django's `test*.py` discovery does
not import it as a test module.
"""
import json
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

# Every module that builds its own ChatGoogleGenerativeAI. Each agent
# constructs the client in __init__, so the patch has to be in place before
# the agent is instantiated.
LLM_MODULES = [
    "trends.services.intelligence",
    "trends.services.prediction",
    "research.services.investigator",
    "research.services.fact_verifier",
    "editorial.services.writer",
    "editorial.services.social",
]


# One payload serves every agent: they all read a parsed dict with
# .get(key, default), so keys they do not recognise are ignored and the merged
# shape satisfies all of them at once.
DEFAULT_PAYLOAD = {
    # --- trends.intelligence ---
    "novelty_score": 8.0,
    "business_relevance_score": 7.5,
    "african_relevance_score": 9.0,
    "developer_interest_score": 8.5,
    "virality_score": 7.0,
    "future_potential": 9.5,
    # --- research.investigator ---
    "key_concepts": ["Agent orchestration", "Tool calling"],
    "timeline": [{"year": 2024, "event": "Multi-agent frameworks reach production"}],
    "technical_explanations": "Agents coordinate through a shared message graph.",
    "advantages_and_limitations": {
        "advantages": ["Parallelism"],
        "limitations": ["Debugging difficulty"],
    },
    "industry_applications": "Customer support triage and research synthesis.",
    "african_opportunities": "Local-language agent tooling for Kenyan fintech.",
    "future_outlook": "Convergence on a small number of orchestration standards.",
    "sources": [{"title": "Example source", "url": "https://example.com/a"}],
    "structured_dossier": "# Dossier\n\nBody text.",
    # --- research.fact_verifier ---
    "confidence_level": 0.88,
    "contradictions_detected": [],
    "unsupported_claims_removed": ["An unsupported market-size claim."],
    "verified_statistics": [{"claim": "Adoption doubled", "source": "https://example.com/a"}],
    "verified_quotes": [],
    "sanitized_text": "# Verified dossier\n\nBody text with claims removed.",
    # --- editorial.writer ---
    "title": "Multi-Agent Orchestration in Production",
    "subtitle": "What changes when agents coordinate themselves",
    "executive_summary": "A short summary of the piece.",
    "hero_paragraph": "The opening paragraph.",
    "introduction": "An introduction.",
    "problem_statement": "The problem being addressed.",
    "historical_context": "How we got here.",
    "current_developments": "What is shipping now.",
    "technical_explanation": "How the graph executes.",
    "industry_impact": "Where this lands commercially.",
    "african_perspective": "What it means for the region.",
    "case_studies": "One deployment, described.",
    "expert_insights": "What practitioners report.",
    "future_predictions": "Where this goes next.",
    "conclusion": "Closing thoughts.",
    "call_to_action": "Subscribe to the Teklora Innovation Dispatch.",
    "faqs": [{"question": "What is orchestration?", "answer": "Coordinating agents."}],
    "meta_description": "Multi-agent orchestration, explained for engineers.",
    "keywords": ["agents", "orchestration", "langgraph"],
    "estimated_reading_time": 8,
    # --- editorial.social ---
    "linkedin_post": "A LinkedIn post.",
    "linkedin_article": "# LinkedIn article",
    "twitter_thread": ["1/ A thread."],
    "facebook_post": "A Facebook post.",
    "instagram_carousel": [],
    "newsletter": "A newsletter issue.",
    "medium_article": "# Medium article",
    "devto_article": "# Dev.to article",
    "podcast_outline": "A podcast outline.",
    "youtube_script": "A YouTube script.",
    "tiktok_script": "A TikTok script.",
    "executive_summary_one_pager": "A one-pager.",
}


class FakeResponse:
    """Mimics the .content attribute the agents read off a model response."""

    def __init__(self, content):
        self.content = content


class FakeChatModel:
    """Returns the same JSON payload for every prompt, and records the calls.

    The agents strip an optional ``` fence before parsing, so returning bare
    JSON exercises the same path.
    """

    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(messages)
        return FakeResponse(json.dumps(self._payload))


@contextmanager
def fake_gemini(overrides=None, modules=None):
    """Patch every agent's model client for the duration of the block.

    `overrides` is merged over DEFAULT_PAYLOAD, so a test that cares about one
    field -- an over-long title, say -- states only that field.
    """
    payload = dict(DEFAULT_PAYLOAD)
    if overrides:
        payload.update(overrides)

    model = FakeChatModel(payload)
    with ExitStack() as stack:
        for module in (modules or LLM_MODULES):
            stack.enter_context(
                patch(
                    f"{module}.ChatGoogleGenerativeAI",
                    # The agents pass model/api key/temperature as kwargs; the
                    # fake ignores them and hands back the same instance, so a
                    # test can assert on model.calls afterwards.
                    new=lambda **kwargs: model,
                )
            )
        yield model


@contextmanager
def broken_gemini(modules=None):
    """Make constructing the model raise, to exercise the fallback drafts.

    Every agent wraps its client construction in try/except and sets
    self.model = None, which is the path taken in production whenever the key
    is missing or the API is unreachable.
    """
    def explode(**kwargs):
        raise RuntimeError("no API key configured")

    with ExitStack() as stack:
        for module in (modules or LLM_MODULES):
            stack.enter_context(
                patch(f"{module}.ChatGoogleGenerativeAI", new=explode)
            )
        yield
