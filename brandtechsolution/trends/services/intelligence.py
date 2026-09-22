"""
Module 2: Trend Intelligence Agent

Scores every discovered trend topic on six criteria and computes the weighted
Priority Score that decides whether it is worth researching.

On the harness since step 6. What left with the rewrite was the heuristic
fallback: when the model was unreachable this agent used to score every topic
from `popularity_score` alone -- 7.0 for business relevance, 7.5 for African
relevance, on every topic -- and the resulting priority scores were high enough
to promote. So an outage did not stop the newsroom; it filled it with topics
nobody had evaluated. An unscored topic now stays `discovered` and is picked up
by the next cycle.
"""
import logging

from pydantic import Field

from ai_workflows.harness.base import Agent, AgentRequest, AgentResult
from ai_workflows.harness.contract import AgentOutput
from ai_workflows.harness.llm import ModelRole
from ai_workflows.harness.persona import Persona
from trends.models import TrendTopic

logger = logging.getLogger(__name__)


class TrendScores(AgentOutput):
    """Six criteria, each 0-10.

    Defaults are 0.0 rather than a comfortable mid-range: a model that returns
    a partial object should produce a topic that fails the threshold, not one
    that drifts through it on filler. `status` is how it declines, and the
    agent routes on that.
    """

    novelty_score: float = Field(default=0.0, ge=0.0, le=10.0)
    business_relevance_score: float = Field(default=0.0, ge=0.0, le=10.0)
    african_relevance_score: float = Field(default=0.0, ge=0.0, le=10.0)
    developer_interest_score: float = Field(default=0.0, ge=0.0, le=10.0)
    virality_score: float = Field(default=0.0, ge=0.0, le=10.0)
    future_potential: float = Field(default=0.0, ge=0.0, le=10.0)
    reasoning: str = ""


# Weighted: African relevance 20%, developer interest 20%, business 20%,
# novelty 15%, virality 15%, future potential 10%. Unchanged by the rewrite.
WEIGHTS = {
    'african_relevance_score': 0.20,
    'developer_interest_score': 0.20,
    'business_relevance_score': 0.20,
    'novelty_score': 0.15,
    'virality_score': 0.15,
    'future_potential': 0.10,
}

PERSONA = Persona(
    name="trend_intelligence",
    role="the Chief Intelligence Officer at Teklora, an African technology media "
         "and innovation publication",
    directives=(
        "Score each trend on novelty, business relevance, African relevance, "
        "developer interest, virality, and 12-36 month future potential.",
        "Judge African relevance by what the topic changes for developers, "
        "startups and enterprises on the continent, not by whether Africa is "
        "mentioned.",
        "Explain the scores briefly enough that an editor can disagree with a "
        "specific number.",
    ),
    constraints=(
        "Do not inflate a score to make a topic publishable.",
        "If the summary is too thin to judge, say so rather than guessing.",
    ),
)

SCORING_PROMPT = """Score this technology trend on each of the six criteria, 0.0 to 10.0.

Trend Title: {title}
Category: {category}
Summary: {summary}
Source: {source}
"""


class TrendIntelligenceAgent(Agent):
    """Evaluates tech trends and computes the Priority Score."""

    name = "trend_intelligence"
    persona = PERSONA
    model_role = ModelRole.ANALYTIC
    tool_suite = "trend_intelligence"

    def __init__(self, priority_threshold: float = 6.5):
        self.priority_threshold = priority_threshold

    # ------------------------------------------------------------------
    # harness entry point
    # ------------------------------------------------------------------

    def run(self, request: AgentRequest) -> AgentResult:
        topic = request.payload["topic"]
        scores = self.ask(
            SCORING_PROMPT.format(
                title=topic.title,
                category=topic.category,
                summary=topic.summary,
                source=topic.source,
            ),
            TrendScores,
        )
        return AgentResult(
            agent=self.name, output=scores,
            abstained=scores.abstained, notes=scores.notes,
        )

    # ------------------------------------------------------------------
    # pipeline surface
    # ------------------------------------------------------------------

    def evaluate_trend(self, topic: TrendTopic) -> TrendTopic | None:
        """Score one topic and promote it if it clears the threshold.

        Returns None when the agent declined to score it -- the newsroom-wide
        convention for an abstention, so a caller that ignores the possibility
        fails on the None rather than proceeding with something invented. The
        topic keeps `discovered` status, so the next cycle tries again, which
        is what you want both for a summary too thin to judge and for a model
        having a bad afternoon.
        """
        logger.info("[trend_intelligence] scoring '%s'", topic.title)

        result = self.execute(AgentRequest(payload={"topic": topic}))
        if result.abstained:
            logger.warning(
                "[trend_intelligence] declined to score '%s': %s",
                topic.title, result.notes or "no reason given",
            )
            return None

        scores = result.output
        for field in WEIGHTS:
            setattr(topic, field, getattr(scores, field))

        topic.priority_score = round(
            sum(getattr(scores, field) * weight for field, weight in WEIGHTS.items()), 2
        )

        if topic.priority_score >= self.priority_threshold:
            topic.status = 'prioritized'
            logger.info(
                "[trend_intelligence] PROMOTED '%s' -> priority %.1f",
                topic.title, topic.priority_score,
            )
        else:
            logger.info(
                "[trend_intelligence] '%s' scored %.1f (below %.1f)",
                topic.title, topic.priority_score, self.priority_threshold,
            )

        topic.save()
        return topic

    def evaluate_all_discovered(self) -> int:
        """Score every pending topic, counting the ones that were actually scored.

        One topic's failure does not abandon the rest: a malformed summary that
        the model cannot parse should cost that topic, not the cycle. The count
        returned is of topics scored, so a run that scored nothing reports zero
        rather than reporting the queue length.
        """
        from ai_workflows.harness.errors import AgentError

        scored = 0
        for topic in TrendTopic.objects.filter(status='discovered'):
            try:
                evaluated = self.evaluate_trend(topic)
            except AgentError:
                logger.exception("[trend_intelligence] failed on '%s'", topic.title)
                continue
            if evaluated is not None:
                scored += 1
        return scored
