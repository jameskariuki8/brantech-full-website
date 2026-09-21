"""The eval cases themselves.

Deliberately starting narrow. A suite of five cases that are run is worth more
than forty that are not, and every case here checks something this codebase
has actually got wrong: a verification gate that could not refuse, and agents
that invent figures because their schema left them no way to decline.
"""
from research.models import ResearchDossier
from research.services.fact_verifier import MIN_CONFIDENCE, FactVerificationAgent
from trends.models import TrendTopic

from ai_workflows.harness.evals.cases import EvalCase, registry
from ai_workflows.harness.evals.graders import (
    DeterministicGrader,
    Grade,
    unsourced_claims,
)

# ============================================================
# Fixtures
# ============================================================

SOURCES = [
    {"title": "Multi-agent orchestration in production", "url": "https://example.com/a"},
    {"title": "A survey of agent frameworks", "url": "https://example.com/b"},
]


def _topic(title="Autonomous AI Multi-Agent Orchestration"):
    return TrendTopic.objects.create(
        title=title,
        summary="Multi-agent systems and enterprise LLM workflow coordination.",
        source="Hacker News",
        source_url="https://news.ycombinator.com/item?id=1000",
        category="Artificial Intelligence",
        keywords=["AI Agents", "Orchestration"],
        popularity_score=8.5,
        growth_velocity=9.0,
        status="prioritized",
    )


def _dossier(body, topic_title=None):
    """A dossier with a controlled body, bypassing the research agent.

    Built directly rather than by running ResearchAgent, because these cases
    are about what the *verifier* does with a given dossier. Letting the
    research agent generate it would make the input vary run to run and the
    verdict unattributable.
    """
    return ResearchDossier.objects.create(
        topic=_topic(topic_title or "Autonomous AI Multi-Agent Orchestration"),
        key_concepts=["Agent orchestration"],
        timeline=[],
        technical_explanations=body,
        advantages_and_limitations={},
        industry_applications="Support triage and research synthesis.",
        african_opportunities="Local-language agent tooling.",
        future_outlook="Convergence on a few orchestration standards.",
        sources=SOURCES,
        structured_dossier=body,
    )


# ============================================================
# Fact verification
# ============================================================

CLEAN_BODY = (
    "Agents coordinate through a shared message graph. Frameworks differ in "
    "how they persist intermediate state between tool calls."
)

CONTRADICTORY_BODY = (
    "The framework reduces latency by eliminating all network round trips. "
    "Each agent hop requires a network round trip to the orchestrator."
)


def _run_verifier(dossier):
    return FactVerificationAgent().verify_dossier(dossier)


registry.register(EvalCase(
    name="verifier.rejects_planted_contradiction",
    agent="fact_verifier",
    description=(
        "A dossier that contradicts itself must not be approved. This is the "
        "case the agent failed for its entire existence: is_approved was the "
        "literal True, so a self-contradictory dossier went to editorial "
        "review indistinguishable from a clean one."
    ),
    setup=lambda: _dossier(CONTRADICTORY_BODY, "Contradictory orchestration claims"),
    run=_run_verifier,
    model_response={
        "confidence_level": 0.88,
        "contradictions_detected": [
            "Claims no network round trips, then requires one per agent hop"
        ],
        "sanitized_text": CONTRADICTORY_BODY,
    },
    graders=[
        DeterministicGrader(
            "refuses_contradiction",
            lambda report, case: (
                Grade.bad("approved a self-contradictory dossier")
                if report.is_approved
                else Grade.ok("refused, as it should")
            ),
        ),
    ],
))


registry.register(EvalCase(
    name="verifier.approves_clean_dossier",
    agent="fact_verifier",
    description=(
        "The other half of the gate. A verifier that refuses everything is as "
        "useless as one that approves everything, and only the pair of cases "
        "together shows the verdict is actually computed."
    ),
    setup=lambda: _dossier(CLEAN_BODY),
    run=_run_verifier,
    model_response={
        "confidence_level": 0.93,
        "contradictions_detected": [],
        "sanitized_text": CLEAN_BODY,
    },
    graders=[
        DeterministicGrader(
            "approves_clean",
            lambda report, case: (
                Grade.ok("approved") if report.is_approved
                else Grade.bad("refused a clean, confident dossier")
            ),
        ),
    ],
))


registry.register(EvalCase(
    name="verifier.refuses_low_confidence",
    agent="fact_verifier",
    description="Below the confidence floor the dossier must not proceed.",
    setup=lambda: _dossier(CLEAN_BODY, "Thinly sourced orchestration claims"),
    run=_run_verifier,
    model_response={
        "confidence_level": max(0.0, MIN_CONFIDENCE - 0.25),
        "contradictions_detected": [],
        "sanitized_text": CLEAN_BODY,
    },
    graders=[
        DeterministicGrader(
            "refuses_low_confidence",
            lambda report, case: (
                Grade.bad(f"approved at {report.confidence_level:.2f} confidence")
                if report.is_approved
                else Grade.ok("refused")
            ),
        ),
    ],
))


registry.register(EvalCase(
    name="verifier.does_not_invent_statistics",
    agent="fact_verifier",
    description=(
        "The sanitized dossier must not acquire figures that were not in the "
        "sources. The fallback draft this codebase shipped for months asserted "
        "'a 40% improvement in performance' out of nothing, and an agent with "
        "a required field and no way to decline will do the same."
    ),
    setup=lambda: _dossier(CLEAN_BODY),
    run=_run_verifier,
    model_response={
        "confidence_level": 0.9,
        "contradictions_detected": [],
        "sanitized_text": CLEAN_BODY,
    },
    graders=[
        DeterministicGrader(
            "no_unsourced_statistics",
            lambda report, case: (
                lambda invented: (
                    Grade.bad(f"invented figures: {invented}")
                    if invented else Grade.ok("no unsourced figures")
                )
            )(unsourced_claims(
                report.verified_dossier,
                CLEAN_BODY + " " + " ".join(s["title"] for s in SOURCES),
            )),
        ),
    ],
))
