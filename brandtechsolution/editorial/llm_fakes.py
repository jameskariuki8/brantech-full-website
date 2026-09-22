"""A stand-in for the model, for tests of the editorial pipeline.

The newsroom tests used to construct the real agents and let them call the
live model. That made the suite depend on the developer's network and on the
API key's quota, and -- worse -- made it dishonest: every agent caught its own
exceptions and fell back to a canned draft, so with the network down the tests
passed without exercising a single line of the code they name. The same tests
then failed when the network was up and the model happened to return a long
title.

Since step 6 there is one patch target instead of six. The agents no longer
build their own clients; they go through `contract.ask`, which resolves one
through `harness.llm.get_model`. Patching it where it is used means a new
agent is covered by this fake the moment it is written, rather than when
somebody remembers to add its module to a list.

Named llm_fakes rather than test_support so Django's `test*.py` discovery does
not import it as a test module.
"""
import json
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

# Every place a chat model is resolved. Patched at the point of use rather
# than the point of definition, because both modules import the name directly.
#
# `gather` is here because step 9 gave the newsroom tools: the verifier and the
# researcher now run a tool loop before they ask for a verdict, and that loop
# resolves its own model. A stub covering only `contract` left a live, billed
# call in the middle of the suite -- the same mistake as the embedder in step 6,
# in a new place. The guard test written for that one is what caught it.
# `contract` iterates candidates so a call that fails at invoke time -- a rate
# limit, a revoked key -- can try the next provider. The fake stands in for the
# iterator, yielding one provider forever's worth of candidates: one.
CANDIDATE_TARGET = "ai_workflows.harness.contract.get_models"

TARGETS = (
    "ai_workflows.harness.gather.get_model",
)

# Kept for anything still importing the old name.
TARGET = CANDIDATE_TARGET

# `Memory.embedder` imports this lazily inside the property, so the definition
# site is the right target here.
EMBEDDER_TARGET = "ai_workflows.harness.llm.get_embedder"


# One payload serves every agent. Each response schema ignores fields it does
# not declare, so the merged shape validates against all of them -- and a test
# that cares about one field states only that field.
DEFAULT_PAYLOAD = {
    # --- trends.intelligence ---
    "novelty_score": 8.0,
    "business_relevance_score": 7.5,
    "african_relevance_score": 9.0,
    "developer_interest_score": 8.5,
    "virality_score": 7.0,
    "future_potential": 9.5,
    "reasoning": "Strong developer signal and direct African applicability.",
    # --- trends.prediction ---
    # Wrapped rather than a bare list: a top-level array has nowhere to carry a
    # status, so a forecaster with nothing to forecast could not say so.
    "predictions": [
        {
            "topic_name": "Autonomous Multi-Agent Orchestration Frameworks",
            "category": "Artificial Intelligence",
            "confidence_score": 0.82,
            "evidence_signals": {"github_growth": "high", "search_intent": "rising"},
            "prediction_report": "Why this will trend, and what it means regionally.",
        }
    ],
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
    """Mimics the .content attribute read off a model response.

    `tool_calls` is empty and explicit. The gathering loop reads it to decide
    whether the model wants to look something up, so a fake without it would
    work by accident on `getattr`, and a reader would have to know that to
    understand why the loop exits after one turn.
    """

    def __init__(self, content):
        self.content = content
        self.tool_calls = []


class _FakeStructured:
    """What `with_structured_output(schema)` hands back."""

    def __init__(self, model, schema):
        self._model = model
        self._schema = schema

    def invoke(self, messages, *args, **kwargs):
        self._model.calls.append(messages)
        return self._schema.model_validate(self._model.payload)


class FakeChatModel:
    """Returns the same payload for every prompt, and records the calls.

    Supports the native structured path by default, because that is the path
    production takes -- Gemini implements `with_structured_output`, so a fake
    that did not would quietly test only the fallback parser. `structured=False`
    forces the text path, for the tests that are about the parser.
    """

    def __init__(self, payload, structured=True):
        self.payload = payload
        self.structured = structured
        self.calls = []

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(messages)
        return FakeResponse(json.dumps(self.payload))

    def with_structured_output(self, schema, **kwargs):
        if not self.structured:
            # `_structured` treats a raising binder as "unsupported" and falls
            # through to plain parsing, which is what a model without the
            # feature does.
            raise NotImplementedError("this fake is in text mode")
        return _FakeStructured(self, schema)

    def bind_tools(self, tools):
        return self


class FakeEmbedder:
    """A deterministic, offline stand-in for the embedding model.

    Not random, and not a hash of the whole string. It buckets words and
    normalises, so two texts that share vocabulary score close together and two
    that do not score near zero -- which means a duplicate-detection test
    written against it measures something. A random vector would make every
    similarity meaningless and the test would pass or fail by coincidence.

    It is a bag of words, so it has none of a real embedder's sense of
    paraphrase. Tests that turn on the *threshold* should say so in their own
    fixtures rather than leaning on this to model semantics it does not have.
    """

    def __init__(self, dimensions=None):
        self._dimensions = dimensions

    @property
    def dimensions(self):
        if self._dimensions is None:
            from knowledge_base.models import EmbeddingSpace

            space = EmbeddingSpace.active()
            # Matching the active space matters: the width is recorded on every
            # row written, and a fake that picked its own would store vectors
            # whose dimensions column disagrees with the vector itself.
            self._dimensions = space.dimensions if space else 64
        return self._dimensions

    def embed_query(self, text):
        import math
        import re
        import zlib

        size = self.dimensions
        vector = [0.0] * size
        for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
            # crc32 rather than hash(): str hashing is salted per process, so
            # the same text would embed differently between runs and a stored
            # vector would stop matching its own query.
            vector[zlib.crc32(word.encode()) % size] += 1.0

        norm = math.sqrt(sum(v * v for v in vector))
        if not norm:
            # An all-zero vector has no direction, so cosine distance against it
            # is undefined; one arbitrary axis keeps empty text comparable.
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]


@contextmanager
def fake_embeddings(embedder=None):
    """Patch embedding resolution for the duration of the block."""
    embedder = embedder or FakeEmbedder()
    with patch(EMBEDDER_TARGET, new=lambda *args, **kwargs: embedder):
        yield embedder


@contextmanager
def fake_gemini(overrides=None, *, structured=True, embeddings=True):
    """Patch model resolution for the duration of the block.

    `overrides` is merged over DEFAULT_PAYLOAD, so a test that cares about one
    field -- an over-long title, say -- states only that field.

    Embeddings are stubbed alongside chat by default. Since step 6 the newsroom
    reaches semantic memory on its own -- the writer remembers each draft and
    the duplicate check recalls against it -- so a fake covering only chat would
    leave a live, billed embedding call in the middle of the test suite. Keeping
    them together means a test cannot acquire one by accident.
    """
    payload = dict(DEFAULT_PAYLOAD)
    if overrides:
        payload.update(overrides)

    model = FakeChatModel(payload, structured=structured)

    def one_candidate(*args, **kwargs):
        from ai_workflows.harness.llm import Provider

        yield Provider.GEMINI, model

    with ExitStack() as stack:
        stack.enter_context(patch(CANDIDATE_TARGET, new=one_candidate))
        for target in TARGETS:
            stack.enter_context(patch(target, new=lambda *args, **kwargs: model))
        if embeddings:
            stack.enter_context(fake_embeddings())
        yield model


@contextmanager
def unavailable_model(message="no API key configured"):
    """Make model resolution raise, as a missing or rejected key does.

    This is the state the six fallback drafts used to cover for. There is now
    nothing to cover for it: every agent raises, the orchestrator records the
    failure, and `harness.alerts` tells somebody.
    """
    from ai_workflows.harness.errors import ModelUnavailable

    def explode(*args, **kwargs):
        raise ModelUnavailable(message, provider="gemini")

    with ExitStack() as stack:
        stack.enter_context(patch(CANDIDATE_TARGET, new=explode))
        for target in TARGETS:
            stack.enter_context(patch(target, new=explode))
        yield
