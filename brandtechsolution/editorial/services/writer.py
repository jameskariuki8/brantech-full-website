"""
Module 6: AI Writer Agent

Turns a verified fact report into a full-length article awaiting human review.

On the harness since step 6. The fallback draft this replaces is the one that
asserted *"Representative enterprise deployments demonstrate a 40% improvement
in performance"* -- a fabricated statistic, hardcoded, in the case-studies
section of every article written while the model was unreachable. It is quoted
in the eval suite and in `errors.py` because it is the clearest example in this
codebase of what a fallback actually costs: not a worse article, a false one,
delivered to an editor with no sign that anything had gone wrong.
"""
import logging

from pydantic import Field

from ai_workflows.harness.base import Agent, AgentRequest, AgentResult
from ai_workflows.harness.contract import AgentOutput, require
from ai_workflows.harness.llm import ModelRole
from ai_workflows.harness.persona import Persona
from editorial.models import EditorialArticle
from research.models import VerifiedFactReport

logger = logging.getLogger(__name__)


class ArticleDraft(AgentOutput):
    """The article, section by section."""

    title: str = ""
    subtitle: str = ""
    executive_summary: str = ""
    hero_paragraph: str = ""
    introduction: str = ""
    problem_statement: str = ""
    historical_context: str = ""
    current_developments: str = ""
    technical_explanation: str = ""
    industry_impact: str = ""
    african_perspective: str = ""
    case_studies: str = ""
    expert_insights: str = ""
    future_predictions: str = ""
    conclusion: str = ""
    call_to_action: str = ""
    faqs: list = Field(default_factory=list)
    meta_description: str = ""
    keywords: list = Field(default_factory=list)
    estimated_reading_time: int = Field(default=6, ge=1, le=120)


PERSONA = Persona(
    name="writer",
    role="the Senior Editor-in-Chief at Teklora Media, Africa's technology "
         "innovation publication",
    directives=(
        "Write long-form, structured, readable journalism with a real opening "
        "and a real argument.",
        "Explain the engineering rather than gesturing at it.",
        "Ground the piece in the African ecosystem -- the developers, the "
        "startups, the enterprise buyers -- as reporting, not as a closing "
        "paragraph.",
        "Write for search without writing for a crawler.",
    ),
    constraints=(
        "Write only from the verified report you are given. It has already had "
        "unsupported claims removed, and you may not put them back.",
        "Do not invent statistics, benchmarks, customer names or quotes. If a "
        "section has no verified material behind it, leave it thin or leave it "
        "empty.",
        "Do not describe a hypothetical deployment as though it happened.",
    ),
)

ARTICLE_PROMPT = """Write the article for this verified research report.

Topic Title: {title}
Verified Facts and Technical Overview:
{verified_text}

African Ecosystem Perspective:
{african_perspective}

Audience: {target_audience}
Tone: {tone}
Target length: about {length_words} words
Reading difficulty: {reading_difficulty}
Focus on: {focus_area}
{continuity}"""

# Step 9. The writer is given `search_knowledge` and not `fetch_url`, and the
# brief is why: it is looking for what Teklora has already said, so the piece
# does not repeat a framing or contradict its own back catalogue. It is not
# looking for material. New facts at the drafting stage are how an unsupported
# claim gets back in after the verifier removed it, which is the failure the
# whole of step 6 was about.
CONTINUITY_BRIEF = """Check what Teklora has already published near this topic.

Topic: {title}
Summary: {verified_text}

Search the knowledge base. Report which past pieces are adjacent, what framing
they used, and anything here that would contradict them. Do not go looking for
new facts about the topic -- that is not your job at this stage.
"""

CONTINUITY_HEADER = """
What Teklora has already published nearby:
{continuity}
Use this for continuity only: avoid repeating a framing, and flag rather than
restate anything that disagrees with it. It is not source material, and nothing
in it may become a claim in this article unless the verified report above also
supports it.
"""

# The sections an article cannot go to review without. The rest may legitimately
# be thin -- not every topic has case studies, and inventing one to fill the
# field is exactly the failure this agent is being rebuilt to stop.
REQUIRED = ("title", "executive_summary", "introduction", "technical_explanation",
            "conclusion")


class AIWriterAgent(Agent):
    """Generates long-form articles from verified research reports."""

    name = "writer"
    persona = PERSONA
    model_role = ModelRole.CREATIVE
    tool_suite = "writer"

    def run(self, request: AgentRequest) -> AgentResult:
        report = request.payload["report"]
        strategy = request.payload.get("strategy") or {}

        continuity = self.gather_evidence(CONTINUITY_BRIEF.format(
            title=report.dossier.topic.title,
            verified_text=report.verified_dossier[:2000],
        ))

        draft = self.ask(
            ARTICLE_PROMPT.format(
                continuity=(
                    CONTINUITY_HEADER.format(continuity=continuity) if continuity else ""
                ),
                title=report.dossier.topic.title,
                verified_text=report.verified_dossier,
                african_perspective=report.dossier.african_opportunities,
                target_audience=strategy.get('target_audience', 'developers'),
                tone=strategy.get('tone', 'Analytical & Authoritative'),
                length_words=strategy.get('length_words', 1600),
                reading_difficulty=strategy.get('reading_difficulty', 'Intermediate'),
                focus_area=strategy.get('focus_area', 'the technology and its adoption'),
            ),
            ArticleDraft,
        )
        if draft.usable:
            require(draft, *REQUIRED, agent=self.name)

        return AgentResult(
            agent=self.name, output=draft,
            abstained=draft.abstained, notes=draft.notes,
        )

    def write_article(self, report: VerifiedFactReport,
                      strategy: dict) -> EditorialArticle | None:
        """Draft the article and queue it for human review.

        Returns None when the agent declined, and writes no article row. A
        topic with no article is visible as a topic with no article; an article
        stitched from the dossier's own sentences is visible as nothing at all,
        which is how the fabricated case study survived to be quoted here.
        """
        logger.info("[writer] drafting '%s'", report.dossier.topic.title)

        existing = EditorialArticle.objects.filter(verification_report=report).first()
        if existing:
            return existing

        result = self.execute(AgentRequest(
            payload={"report": report, "strategy": strategy}
        ))
        if result.abstained:
            logger.warning(
                "[writer] declined to draft '%s': %s",
                report.dossier.topic.title, result.notes or "no reason given",
            )
            return None

        draft = result.output
        topic = report.dossier.topic

        article = EditorialArticle.objects.create(
            topic=topic,
            verification_report=report,
            title=draft.title,
            subtitle=draft.subtitle,
            executive_summary=draft.executive_summary,
            hero_paragraph=draft.hero_paragraph,
            introduction=draft.introduction,
            problem_statement=draft.problem_statement,
            historical_context=draft.historical_context,
            current_developments=draft.current_developments,
            technical_explanation=draft.technical_explanation,
            industry_impact=draft.industry_impact,
            african_perspective=draft.african_perspective,
            case_studies=draft.case_studies,
            expert_insights=draft.expert_insights,
            future_predictions=draft.future_predictions,
            conclusion=draft.conclusion,
            call_to_action=(
                draft.call_to_action
                or EditorialArticle._meta.get_field('call_to_action').default
            ),
            faqs=draft.faqs,
            # References come from the dossier, not from the draft. The writer
            # is not asked for sources precisely so that it cannot mint one.
            references=report.dossier.sources,
            meta_description=draft.meta_description or draft.executive_summary[:150],
            keywords=draft.keywords or topic.keywords,
            target_audience=strategy.get('target_audience', 'developers'),
            tone=strategy.get('tone', 'Analytical & Authoritative'),
            reading_time_minutes=draft.estimated_reading_time,
            estimated_reading_difficulty=strategy.get('reading_difficulty', 'Intermediate'),
            status='review_pending',
        )

        # Remember it, so the duplicate check has something to compare against.
        # Done here rather than at publish because a draft already in the review
        # queue should stop the newsroom researching the same story again.
        self._remember(article)

        topic.status = 'approved_for_article'
        topic.save()

        logger.info(
            "[writer] draft #%d complete: '%s' (awaiting review)",
            article.id, article.title,
        )
        return article

    @staticmethod
    def _remember(article: EditorialArticle):
        """Add the draft to semantic memory for duplicate detection."""
        from ai_workflows.harness.errors import MemoryUnavailable
        from ai_workflows.harness.memory import Memory

        text = f"{article.title}\n\n{article.subtitle}\n\n{article.executive_summary}"
        try:
            Memory(scope="editorial").remember(
                text, title=article.title, kind="article", obj=article,
            )
        except MemoryUnavailable:
            # Not fatal, and deliberately not silent. The article is written
            # and correct; what is lost is that the *next* cycle may not
            # recognise this topic as covered. Failing the draft over it would
            # throw away good work to protect against a duplicate.
            logger.exception(
                "[writer] could not remember article #%d; duplicate detection "
                "will not see it until it is re-indexed", article.id,
            )
