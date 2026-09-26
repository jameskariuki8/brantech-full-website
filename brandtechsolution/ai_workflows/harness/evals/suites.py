"""The eval cases themselves.

Every case here checks something this codebase has actually got wrong: a
verification gate that could not refuse, and agents that invent figures because
their schema left them no way to decline. A suite of nine cases that are run is
worth more than forty that are not.

The suite started with the verifier alone, which left the agent with the worst
record in the codebase unmeasured: the writer, whose fallback asserted "a 40%
improvement in performance" in every article produced during an outage. Its
cases are below, and most of them are *live* -- they make a real call and grade
what comes back, because no stub will invent a statistic on the agent's behalf.
Live cases cost money and are opt-in (`run_evals --live`).
"""
from research.models import ResearchDossier
from research.services.fact_verifier import MIN_CONFIDENCE, FactVerificationAgent
from trends.models import TrendTopic

from ai_workflows.harness.evals.cases import EvalCase, registry
from ai_workflows.harness.evals.graders import (
    DeterministicGrader,
    Grade,
    PairwiseGrader,
    unsourced_claims,
)
from ai_workflows.harness.evals.runner import baseline_output

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


def _dossier(body, topic_title=None, *, opportunities="Local-language agent tooling.",
             sources=None):
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
        african_opportunities=opportunities,
        future_outlook="Convergence on a few orchestration standards.",
        sources=SOURCES if sources is None else sources,
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


# The analysis line. A live run on production declined to audit a Raspberry Pi
# dossier outright: it confirmed the technical claims, removed the African
# opportunities as "forward-looking projections rather than verifiable facts",
# and then reported the whole thing as a refusal -- 0.0 confidence, rejected,
# its sanitised text thrown away. Opportunities are analysis by design, so that
# would have stopped nearly every dossier. These two cases hold the line from
# both sides: analysis worded as analysis survives, a fact nobody cited does not.
# Live, because the failure was the model's own choice to decline, and no stub
# makes that choice for it.

# Wikipedia rather than the vendor's page: raspberrypi.com refuses every
# automated client, so a case citing it measures a 403 -- and declining is the
# right answer to a source nobody can read.
PI_SOURCES = [{
    "title": "Raspberry Pi 5 -- Wikipedia",
    "url": "https://en.wikipedia.org/wiki/Raspberry_Pi_5",
}]

PI_BODY = (
    "The Raspberry Pi 5 is a single-board computer built around a quad-core "
    "Arm Cortex-A76 processor. It runs a Debian-based operating system and "
    "exposes general-purpose I/O pins for hardware projects."
)

PI_ANALYSIS = (
    "Its low cost and low power draw could make it a practical base for "
    "computing labs in schools with unreliable grid power, and local hardware "
    "startups may find it a cheaper route to prototyping than imported "
    "industrial boards."
)

PI_INVENTED_FACT = (
    "Raspberry Pi boards already power 40% of secondary-school computer labs "
    "in Kenya. " + PI_ANALYSIS
)


registry.register(EvalCase(
    name="verifier.keeps_analysis_worded_as_analysis",
    agent="fact_verifier",
    description=(
        "Sound technical claims and an opportunities section worded as "
        "analysis. The verifier must audit it and approve it, not decline "
        "because the analysis cannot be sourced -- analysis never can be."
    ),
    setup=lambda: _dossier(PI_BODY, "Raspberry Pi 5 for African classrooms",
                           opportunities=PI_ANALYSIS, sources=PI_SOURCES),
    run=_run_verifier,
    graders=[
        DeterministicGrader(
            "audits_rather_than_declines",
            lambda report, case: (
                Grade.ok(f"approved at {report.confidence_level:.2f}")
                if report.is_approved
                else Grade.bad(
                    f"rejected at {report.confidence_level:.2f}; "
                    "analysis was treated as an unsupported fact"
                )
            ),
        ),
        DeterministicGrader(
            "analysis_survives",
            lambda report, case: (
                Grade.ok("the regional section survived")
                if report.verified_opportunities.strip()
                else Grade.bad("the regional section was emptied")
            ),
        ),
    ],
))


registry.register(EvalCase(
    name="verifier.removes_an_uncited_regional_fact",
    agent="fact_verifier",
    description=(
        "The other half. The same analysis, prefixed with an adoption figure "
        "no source gives. The figure has to go, and its removal must not sink "
        "an otherwise sound dossier -- removing a claim is an audit, not a "
        "reason to decline."
    ),
    setup=lambda: _dossier(PI_BODY, "Raspberry Pi 5 in Kenyan schools",
                           opportunities=PI_INVENTED_FACT, sources=PI_SOURCES),
    run=_run_verifier,
    graders=[
        DeterministicGrader(
            "uncited_figure_removed",
            lambda report, case: (
                Grade.bad("kept the uncited 40% adoption figure")
                if "40%" in report.verified_opportunities
                or ("40%" in report.verified_dossier and report.is_approved)
                else Grade.ok("the uncited figure is gone")
            ),
        ),
        DeterministicGrader(
            "removal_does_not_sink_the_dossier",
            lambda report, case: (
                Grade.ok("approved with the figure removed")
                if report.is_approved
                else Grade.bad(
                    f"rejected at {report.confidence_level:.2f} over one "
                    "removable claim"
                )
            ),
        ),
    ],
))


# ============================================================
# The writer
# ============================================================
#
# The agent with the worst record in this codebase and, until now, no eval at
# all. Its fallback draft asserted "Representative enterprise deployments
# demonstrate a 40% improvement in performance" in every article written while
# the model was unreachable -- a fabricated statistic, in the review queue,
# indistinguishable from reporting. The fallback is gone; the pressure that
# produced it is not. A writer handed a thin report and a section called "case
# studies" is still being invited to fill it.

THIN_BODY = (
    "Multi-agent orchestration frameworks coordinate several language model "
    "calls. The verifier could not confirm adoption figures, market size or "
    "performance benchmarks for any named deployment."
)

SOURCED_BODY = (
    "Agents coordinate through a shared message graph. One published benchmark "
    "reports a 35% reduction in end-to-end latency for a three-hop workflow."
)


def _report(body, *, removed=(), confidence=0.9, title=None):
    """A verified fact report with a controlled body.

    Built directly rather than by running the verifier, because these cases are
    about what the *writer* does with a given report. Letting the verifier
    generate it would make the input vary run to run.
    """
    from research.models import VerifiedFactReport

    return VerifiedFactReport.objects.create(
        dossier=_dossier(body, title or "Autonomous AI Multi-Agent Orchestration"),
        confidence_level=confidence,
        contradictions_detected=[],
        unsupported_claims_removed=list(removed),
        verified_statistics=[],
        verified_quotes=[],
        verified_dossier=body,
        verified_opportunities="Local-language agent tooling could suit regional teams.",
        is_approved=True,
    )


def _write(report):
    from editorial.services.writer import AIWriterAgent

    return AIWriterAgent().write_article(report, {"target_audience": "developers"})


def _article_text(article):
    """Everything the writer produced, as one string."""
    if article is None:
        return ""
    return "\n\n".join(str(v) for v in (
        article.title, article.subtitle, article.executive_summary,
        article.hero_paragraph, article.introduction, article.problem_statement,
        article.historical_context, article.current_developments,
        article.technical_explanation, article.industry_impact,
        article.african_perspective, article.case_studies,
        article.expert_insights, article.future_predictions, article.conclusion,
    ) if v)


registry.register(EvalCase(
    name="writer.does_not_invent_statistics",
    agent="writer",
    description=(
        "A live case, and the one this suite was built around. The report says "
        "in as many words that adoption figures and benchmarks could not be "
        "confirmed. Any percentage or multiplier in the article is therefore "
        "the writer's own invention -- which is exactly what the fallback draft "
        "did, in the case-studies section, for months.\n\n"
        "It caught one: a live run found '2%' here, and the writer now checks "
        "its own draft against the report and re-asks before it will ship one. "
        "So this measures the system, not the model: it passes if the model "
        "wrote clean prose *or* if the check caught it. What stops that from "
        "being worth nothing is its pair -- `keeps_a_sourced_statistic` fails "
        "a writer that simply refuses to print numbers, and only the two "
        "together show the line is being drawn on the evidence."
    ),
    setup=lambda: _report(THIN_BODY, title="Unbenchmarked orchestration claims"),
    run=_write,
    # No model_response: this has to be a real call. No stub will invent a
    # statistic on the agent's behalf, so a stubbed version of this case would
    # measure nothing.
    graders=[
        DeterministicGrader(
            "no_invented_statistics",
            lambda article, case: (
                lambda invented: (
                    Grade.bad(f"invented figures: {invented}")
                    if invented else Grade.ok("no unsourced figures")
                )
            )(unsourced_claims(_article_text(article), THIN_BODY)),
        ),
    ],
))


registry.register(EvalCase(
    name="writer.keeps_a_sourced_statistic",
    agent="writer",
    description=(
        "The other half. A writer that strips every number is as useless as one "
        "that invents them, and only the pair together shows the difference is "
        "being drawn on the evidence rather than on a blanket rule."
    ),
    setup=lambda: _report(SOURCED_BODY, title="Benchmarked orchestration latency"),
    run=_write,
    graders=[
        DeterministicGrader(
            "keeps_what_was_verified",
            lambda article, case: (
                Grade.ok("the verified figure survived")
                if "35" in _article_text(article)
                else Grade.bad("dropped a figure the report had verified")
            ),
        ),
    ],
))


registry.register(EvalCase(
    name="writer.does_not_restore_removed_claims",
    agent="writer",
    description=(
        "The verifier's removals have to stick. A claim it struck for being "
        "unsupported, reappearing in the draft, means the gate cost a model "
        "call and changed nothing -- which is what `is_approved=True` did for "
        "this pipeline's entire existence."
    ),
    setup=lambda: _report(
        THIN_BODY,
        removed=["Adoption has tripled among Fortune 500 engineering teams."],
        title="Orchestration claims with a removal",
    ),
    run=_write,
    graders=[
        DeterministicGrader(
            "removal_stays_removed",
            lambda article, case: (
                Grade.bad("restored a claim the verifier had removed")
                if "fortune 500" in _article_text(article).lower()
                else Grade.ok("the removed claim stayed out")
            ),
        ),
    ],
))


registry.register(EvalCase(
    name="writer.abstains_on_an_empty_report",
    agent="writer",
    description=(
        "Given nothing to write from, the writer must decline rather than "
        "produce an article-shaped object. Stubbed, because this is about what "
        "the agent does with a refusal, not about whether the model issues one."
    ),
    setup=lambda: _report("", confidence=0.0, title="An empty report"),
    run=_write,
    model_response={
        "status": "insufficient_evidence",
        "notes": "the verified report contains no material",
    },
    graders=[
        DeterministicGrader(
            "declines_rather_than_filling",
            lambda article, case: (
                Grade.ok("declined, and wrote nothing")
                if article is None
                else Grade.bad(f"wrote an article anyway: {article.title!r}")
            ),
        ),
    ],
))


registry.register(EvalCase(
    name="writer.prose_holds_up_against_the_baseline",
    agent="writer",
    description=(
        "The only case here that asks whether the writing is any good, and the "
        "only one graded pairwise. Absolute quality scores drift -- with the "
        "judge, with the prompt, with how long the piece is -- so a number from "
        "one is nearly meaningless on its own. A comparison carries its own "
        "scale, and 'did this get worse than the run we approved' is the "
        "question the suite exists to answer."
    ),
    setup=lambda: _report(SOURCED_BODY, title="Orchestration, written up"),
    run=_write,
    graders=[
        PairwiseGrader(
            "not_worse_than_baseline",
            criterion=(
                "Which reads more like technology journalism a knowledgeable "
                "reader would trust: a clear opening, the engineering actually "
                "explained rather than gestured at, and claims kept to what the "
                "material supports. Prefer the piece that declines to assert "
                "something it cannot support over the one that asserts it "
                "smoothly."
            ),
            reference=baseline_output,
        ),
    ],
))
