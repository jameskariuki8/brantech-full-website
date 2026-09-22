"""
Module 4: Fact Verification Agent

Audits a research dossier for unsupported claims, contradictions and invented
figures, and decides whether it may be written up.

On the harness since step 6. This agent's fallback was the worst of the six:
with the model unreachable it returned 0.90 confidence and no contradictions,
which `_approves` then reads as a pass. The one gate in the pipeline whose
entire purpose is to refuse became, on any outage, a gate that approved
everything -- and did it while reporting a specific, confident-looking number.
An audit that could not be performed is now a refusal.
"""
import json
import logging

from pydantic import Field

from ai_workflows.harness.base import Agent, AgentRequest, AgentResult
from ai_workflows.harness.contract import AgentOutput, ask, require
from ai_workflows.harness.llm import ModelRole
from ai_workflows.harness.persona import Persona
from research.models import ResearchDossier, VerifiedFactReport

logger = logging.getLogger(__name__)

# Below this, the agent is not confident enough for the dossier to be written
# up as an article. Deliberately a named constant rather than a literal: the
# value is a judgement call and will be tuned, and a reader needs to see that
# it is one.
MIN_CONFIDENCE = 0.6


class FactAudit(AgentOutput):
    """The audit findings.

    `confidence_level` defaults to 0.0, not to a comfortable number. A partial
    response should fail the gate. That is the whole asymmetry this agent
    exists to hold: approving something unread is a published fabrication,
    refusing something sound is a topic that waits.
    """

    confidence_level: float = Field(default=0.0, ge=0.0, le=1.0)
    contradictions_detected: list = Field(default_factory=list)
    unsupported_claims_removed: list = Field(default_factory=list)
    verified_statistics: list = Field(default_factory=list)
    verified_quotes: list = Field(default_factory=list)
    sanitized_text: str = ""


PERSONA = Persona(
    name="fact_verifier",
    role="the Lead Fact Verification Editor at Teklora",
    directives=(
        "Audit the dossier against its own cited sources and against what is "
        "established in the field.",
        "Name every contradiction you find, quoting the two statements that "
        "disagree.",
        "Remove claims the dossier does not support rather than softening them.",
        "Set the confidence score on the evidence, and treat a dossier you "
        "cannot check as one you are not confident about.",
    ),
    constraints=(
        "Do not add facts, figures or citations during sanitisation. Your "
        "output may only contain what the dossier already claimed.",
        "Do not approve a dossier because it reads well.",
        "If the dossier gives you nothing to verify against, decline rather "
        "than issuing a confidence score you cannot support.",
    ),
)

VERIFICATION_PROMPT = """Audit this research dossier for factual accuracy, unsupported
claims and internal contradictions.

Topic Title: {title}
Technical Explanation: {technical_explanations}
African Opportunities: {african_opportunities}
Sources Cited: {sources}

Return the sanitised text with unsupported claims removed, the contradictions
you found, the statistics and quotes you were able to verify, and an overall
confidence level between 0.0 and 1.0.
"""


class FactVerificationAgent(Agent):
    """Fact-checks research dossiers before article generation."""

    name = "fact_verifier"
    persona = PERSONA
    model_role = ModelRole.PRECISE
    tool_suite = "fact_verifier"

    # This agent's verdicts are compared across runs by the eval suite. A
    # silent failover to another model mid-comparison would make a change in
    # score unattributable, which is the one thing the suite exists to give.
    allow_fallback = False

    def run(self, request: AgentRequest) -> AgentResult:
        dossier = request.payload["dossier"]

        audit = ask(
            self.voiced_persona(),
            VERIFICATION_PROMPT.format(
                title=dossier.topic.title,
                technical_explanations=dossier.technical_explanations,
                african_opportunities=dossier.african_opportunities,
                sources=json.dumps(dossier.sources),
            ),
            FactAudit,
            role=self.model_role,
            agent=self.name,
        )
        if audit.usable:
            # An audit that sanitised the dossier down to nothing has not
            # audited it; the writer would be handed an empty body.
            require(audit, "sanitized_text", agent=self.name)

        return AgentResult(
            agent=self.name, output=audit,
            abstained=audit.abstained, notes=audit.notes,
        )

    def verify_dossier(self, dossier: ResearchDossier) -> VerifiedFactReport:
        """Audit `dossier` and record the verdict.

        Always returns a report, including when the agent declined -- a
        refusal is a verdict and belongs in the record, so an editor looking at
        the topic can see it was considered and why it stopped. The report is
        simply not approved.
        """
        logger.info("[fact_verifier] auditing '%s'", dossier.topic.title)

        existing = VerifiedFactReport.objects.filter(dossier=dossier).first()
        if existing:
            return existing

        result = self.execute(AgentRequest(payload={"dossier": dossier}))
        audit = result.output

        if result.abstained:
            logger.warning(
                "[fact_verifier] declined to audit '%s': %s",
                dossier.topic.title, audit.notes or "no reason given",
            )
            return VerifiedFactReport.objects.create(
                dossier=dossier,
                confidence_level=0.0,
                contradictions_detected=[],
                unsupported_claims_removed=[],
                verified_statistics=[],
                verified_quotes=[],
                # The unverified dossier, not a sanitised one -- nothing was
                # sanitised. Storing the original under `verified_dossier` on
                # an unapproved report keeps the text available for an editor
                # without anything downstream being able to mistake it for
                # audited prose, because `is_approved` is what gates that.
                verified_dossier=dossier.structured_dossier,
                is_approved=False,
            )

        report = VerifiedFactReport.objects.create(
            dossier=dossier,
            confidence_level=audit.confidence_level,
            contradictions_detected=audit.contradictions_detected,
            unsupported_claims_removed=audit.unsupported_claims_removed,
            verified_statistics=audit.verified_statistics,
            verified_quotes=audit.verified_quotes,
            verified_dossier=audit.sanitized_text,
            is_approved=self._approves(audit.confidence_level,
                                       audit.contradictions_detected),
        )

        if report.is_approved:
            logger.info(
                "[fact_verifier] verified '%s' with %.0f%% confidence.",
                dossier.topic.title, report.confidence_level * 100,
            )
        else:
            logger.warning(
                "[fact_verifier] REJECTED '%s': %.0f%% confidence, "
                "%d contradiction(s).",
                dossier.topic.title, report.confidence_level * 100,
                len(report.contradictions_detected),
            )
        return report

    @staticmethod
    def _approves(confidence, contradictions) -> bool:
        """Decide whether this dossier may be written up.

        This used to be the literal `is_approved=True`, which made the whole
        agent decorative: it reported contradictions and a confidence score,
        then approved regardless, and nothing downstream looked at the flag
        anyway. The only test covering it asserted a constant.

        The rule uses what the agent already returns rather than inventing a
        new signal. A detected contradiction is disqualifying on its own -- the
        agent has said the dossier disagrees with itself, and averaging that
        away against a high confidence score would be perverse.
        """
        if contradictions:
            return False
        try:
            return float(confidence) >= MIN_CONFIDENCE
        except (TypeError, ValueError):
            # A model that returned something non-numeric has not given us
            # grounds to approve.
            return False
