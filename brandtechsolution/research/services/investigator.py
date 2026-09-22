"""
Module 3: Research Agent

Builds a structured Research Dossier for a prioritised trend topic: concepts,
timeline, technical breakdown, tradeoffs, African opportunities, sources.

On the harness since step 6. The fallback dossier is gone. It used to fill
every field with the topic's own title -- "Great opportunity for African
engineers and startups to leverage {title}" -- which then went to the fact
verifier, which had its own fallback approving it at 90% confidence, and on to
the writer. Three agents could be down and the pipeline would still deliver an
article to the review queue. The dossier now either contains research or does
not exist.
"""
import logging

from pydantic import Field

from ai_workflows.harness.base import Agent, AgentRequest, AgentResult
from ai_workflows.harness.contract import AgentOutput, require
from ai_workflows.harness.llm import ModelRole
from ai_workflows.harness.persona import Persona
from research.models import ResearchDossier
from trends.models import TrendTopic

logger = logging.getLogger(__name__)


class Dossier(AgentOutput):
    """The research findings.

    The list and dict fields are loose on purpose. Each one lands in a
    JSONField whose shape the prompt describes but the database does not
    enforce, and tightening the schema here without migrating the existing rows
    would mean the agent could no longer read back what it had already written.
    """

    key_concepts: list = Field(default_factory=list)
    timeline: list = Field(default_factory=list)
    technical_explanations: str = ""
    advantages_and_limitations: dict = Field(default_factory=dict)
    industry_applications: str = ""
    african_opportunities: str = ""
    future_outlook: str = ""
    sources: list = Field(default_factory=list)
    structured_dossier: str = ""


PERSONA = Persona(
    name="research",
    role="an Investigative Technology Journalist and Research Specialist for "
         "Teklora Media",
    directives=(
        "Research the topic in depth: the core concepts, how it actually works "
        "under the hood, the tradeoffs, and who is adopting it.",
        "Treat African relevance as reporting rather than decoration -- name "
        "the markets, the constraints and the specific opportunities.",
        "Cite sources you can name. A citation is a claim about where "
        "something came from, and a wrong one is worse than none.",
    ),
    constraints=(
        "Do not invent statistics, funding figures, adoption rates or quotes.",
        "Do not fabricate a citation, a URL or a milestone date to fill a field.",
        "If you cannot research the topic from what you were given, decline "
        "rather than producing a plausible-looking dossier.",
    ),
)

RESEARCH_PROMPT = """Research this technology topic and compile a dossier.

Topic Title: {title}
Category: {category}
Summary Context: {summary}
Initial Source: {source} ({source_url})

Cover:
1. Key concepts -- 3-5 core concepts with definitions.
2. Timeline -- the milestones that led here.
3. Technical explanation -- the architectural and engineering breakdown.
4. Advantages and limitations -- including bottlenecks and tradeoffs.
5. Industry applications -- who is adopting it and how.
6. African opportunities -- concrete strategic and developer opportunities.
7. Future outlook -- the next 2-5 years.
8. Sources -- reference citations with titles and URLs.

Also compile the whole thing as a markdown dossier in `structured_dossier`.
{evidence}"""

# What the agent goes and reads before it writes anything down. Step 9: it
# cites sources, so it should be able to open them -- and it can now see what
# the newsroom has already established rather than starting from nothing on a
# topic it covered last month.
EVIDENCE_BRIEF = """Research this topic before writing it up.

Topic Title: {title}
Category: {category}
Summary Context: {summary}
Initial Source: {source} ({source_url})

Read the initial source. Search what the newsroom has already established
about this area. Report what you actually found, with the URLs, and say which
parts of the topic you could not find material for.
"""

EVIDENCE_HEADER = """
What you found when you looked:
{evidence}
Build the dossier from this. Cite only sources you actually read, and leave a
section thin rather than filling it from memory.
"""

# What a dossier must contain to be worth passing to verification. A dossier
# with no technical explanation and no sources is not research, whatever the
# status field says.
REQUIRED = ("technical_explanations", "structured_dossier", "sources")


class ResearchAgent(Agent):
    """Investigates technology topics and produces a ResearchDossier."""

    name = "research"
    persona = PERSONA
    model_role = ModelRole.ANALYTIC
    tool_suite = "research"

    def run(self, request: AgentRequest) -> AgentResult:
        topic = request.payload["topic"]
        fields = {
            "title": topic.title,
            "category": topic.category,
            "summary": topic.summary,
            "source": topic.source,
            "source_url": topic.source_url or "",
        }

        evidence = self.gather_evidence(EVIDENCE_BRIEF.format(**fields))

        findings = self.ask(
            RESEARCH_PROMPT.format(
                evidence=EVIDENCE_HEADER.format(evidence=evidence) if evidence else "",
                **fields,
            ),
            Dossier,
        )
        if findings.usable:
            require(findings, *REQUIRED, agent=self.name)

        return AgentResult(
            agent=self.name, output=findings,
            abstained=findings.abstained, notes=findings.notes,
        )

    def conduct_research(self, topic: TrendTopic) -> ResearchDossier | None:
        """Research `topic` and store the dossier.

        Returns None when the agent declined, and writes no dossier row. The
        topic is left for the orchestrator to reject: an un-researched topic
        must not reach the verifier, because the verifier's job is to audit
        research and it has nothing to audit.
        """
        logger.info("[research] researching '%s'", topic.title)

        existing = ResearchDossier.objects.filter(topic=topic).first()
        if existing:
            return existing

        topic.status = 'researching'
        topic.save()

        result = self.execute(AgentRequest(payload={"topic": topic}))
        if result.abstained:
            logger.warning(
                "[research] declined to research '%s': %s",
                topic.title, result.notes or "no reason given",
            )
            return None

        findings = result.output
        dossier = ResearchDossier.objects.create(
            topic=topic,
            key_concepts=findings.key_concepts,
            timeline=findings.timeline,
            technical_explanations=findings.technical_explanations,
            advantages_and_limitations=findings.advantages_and_limitations,
            industry_applications=findings.industry_applications,
            african_opportunities=findings.african_opportunities,
            future_outlook=findings.future_outlook,
            sources=findings.sources,
            structured_dossier=findings.structured_dossier,
        )
        logger.info("[research] dossier #%d created for '%s'", dossier.id, topic.title)
        return dossier
