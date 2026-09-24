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
from ai_workflows.harness.contract import AgentOutput, require
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

    # The African opportunities section, audited on its own. It is the one part
    # of a dossier that is mostly analysis by design -- "this could suit..." --
    # and it used to be handed to the writer raw, so nothing removed from it
    # ever stayed removed.
    sanitized_opportunities: str = ""


PERSONA = Persona(
    name="fact_verifier",
    role="the Lead Fact Verification Editor at Teklora",
    directives=(
        "Audit the dossier against its own cited sources and against what is "
        "established in the field.",
        "Name every contradiction you find, quoting the two statements that "
        "disagree.",
        "Remove claims the dossier does not support rather than softening them.",
        "Tell facts from analysis. A statement about what exists, happened or "
        "was measured is a fact and needs support. A forward-looking judgement "
        "worded as one -- 'could', 'may', 'is well placed to' -- is analysis: "
        "keep it. If it rests on a premise nobody supported, remove or soften "
        "that premise and keep the rest of the analysis.",
        "A premise that is common knowledge in the field needs no citation. "
        "One that is specific -- a price, a wattage, a market share, a named "
        "deployment -- does.",
        "An opportunity asserted as a current reality -- adoption, deployments, "
        "market share that nobody cited -- is a fact, and unsupported. Remove "
        "it, or keep it only reworded as the analysis it actually is.",
        "Set the confidence score on the text you return, not the dossier you "
        "were given: it answers whether what survived your audit is sound "
        "enough to write up. A claim you removed no longer counts against it, "
        "and neither does analysis you kept. Treat text you could not check as "
        "text you are not confident about.",
    ),
    constraints=(
        "Do not add facts, figures or citations during sanitisation. Your "
        "output may only contain what the dossier already claimed.",
        "Do not approve a dossier because it reads well.",
        "Decline only if you could check nothing at all -- no source to read, "
        "nothing established to compare against. Removing some claims is an "
        "audit, not a reason to decline: return what survived.",
    ),
)

# What the agent is asked to go and check, before it is asked for a verdict.
# Two calls rather than one: a call asked to research a question *and* emit a
# schema does neither well, and splitting them means the evidence exists as
# text between the two, where it can be stored and read by a human wondering
# why the agent decided what it did.
EVIDENCE_BRIEF = """Check the claims in this dossier.

Topic Title: {title}
Technical Explanation: {technical_explanations}
African Opportunities: {african_opportunities}
Sources Cited: {sources}

Read the cited sources and see whether they say what the dossier says they
say. Search what the newsroom has already established and see whether this
agrees with it. Report what each source actually supports, and say plainly
which claims you could not check.
"""

VERIFICATION_PROMPT = """Audit this research dossier for factual accuracy, unsupported
claims and internal contradictions.

Topic Title: {title}
Technical Explanation: {technical_explanations}
African Opportunities: {african_opportunities}
Sources Cited: {sources}
{evidence}
Return the sanitised text with unsupported claims removed, the African
Opportunities section audited on its own in `sanitized_opportunities` (analysis
kept as analysis, unsupported facts removed), the contradictions you found, the
statistics and quotes you were able to verify, and an overall confidence level
between 0.0 and 1.0.
"""

EVIDENCE_HEADER = """
What you found when you checked:
{evidence}
Base your confidence on this. A claim you could not check is not a verified
claim, however plausible it reads.
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
        fields = {
            "title": dossier.topic.title,
            "technical_explanations": dossier.technical_explanations,
            "african_opportunities": dossier.african_opportunities,
            "sources": json.dumps(dossier.sources),
        }

        # Step 9. Until now this agent checked claims against the model's own
        # weights, which is a strange thing for a fact checker to do: asking a
        # language model whether it believes itself. It now reads the sources
        # the dossier cites before it forms a view.
        evidence = self.gather_evidence(EVIDENCE_BRIEF.format(**fields))

        audit = self.ask(
            VERIFICATION_PROMPT.format(
                evidence=EVIDENCE_HEADER.format(evidence=evidence) if evidence else "",
                **fields,
            ),
            FactAudit,
        )
        if audit.usable:
            # An audit that sanitised the dossier down to nothing has not
            # audited it; the writer would be handed an empty body.
            require(audit, "sanitized_text", agent=self.name)

        return AgentResult(
            agent=self.name, output=audit,
            abstained=audit.abstained, notes=audit.notes,
            metadata={"evidence": evidence},
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
        evidence = result.metadata.get("evidence", "")

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
                verification_evidence=evidence,
                # Left empty rather than copied: an unapproved report is never
                # drafted from, and an empty section cannot leak.
                verified_opportunities="",
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
            verified_opportunities=audit.sanitized_opportunities,
            # Its own column, deliberately not appended to verified_dossier.
            # That field is what the writer drafts from, so a checking
            # transcript in it would put fetched page text -- and its numbers --
            # into the article prompt, past the sanitisation that had just
            # removed unsupported claims. It would also reach the eval that
            # looks for invented figures and read as the verifier inventing
            # them. A verdict still has to be reviewable, so it is kept; it is
            # just kept somewhere that only a reviewer looks.
            verification_evidence=evidence,
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
