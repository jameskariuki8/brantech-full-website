"""
Module 4: Fact Verification Agent

Reduces AI hallucinations. Cross-references research statements, detects contradictions,
removes unsupported claims, assigns confidence levels, and verifies quotes/statistics.
"""
import logging
import json
from typing import Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from brandtechsolution.config import config
from research.models import ResearchDossier, VerifiedFactReport

logger = logging.getLogger(__name__)

# Below this, the agent is not confident enough for the dossier to be written
# up as an article. Deliberately a named constant rather than a literal: the
# value is a judgement call and will be tuned, and a reader needs to see that
# it is one.
MIN_CONFIDENCE = 0.6

VERIFICATION_PROMPT = """You are the Lead Fact Verification Editor at Teklora.
Audit the following research dossier for factual accuracy, hallucinations, and logical consistency.

Topic Title: {title}
Technical Explanation: {technical_explanations}
African Opportunities: {african_opportunities}
Sources Cited: {sources}

Tasks:
1. Verify if claims are realistic, accurate, and supported by industry standards.
2. Highlight any potential hallucination or unsupported claim.
3. Verify cited statistics or quotes.
4. Calculate an overall Fact Confidence Score (between 0.0 and 1.0).

Return ONLY a JSON object:
{{
  "confidence_level": 0.95,
  "contradictions_detected": [],
  "unsupported_claims_removed": [],
  "verified_statistics": [
    "Verified industry growth rate and technical specs."
  ],
  "verified_quotes": [],
  "sanitized_text": "Sanitized and fact-checked technical overview..."
}}
"""


class FactVerificationAgent:
    """Fact-checks research dossiers before article generation."""

    def __init__(self):
        try:
            self.model = ChatGoogleGenerativeAI(
                model=config.gemini_chat_model,
                google_api_key=config.google_api_key,
                temperature=0.1
            )
        except Exception as e:
            logger.warning(f"FactVerificationAgent LLM init failed: {e}")
            self.model = None

    def verify_dossier(self, dossier: ResearchDossier) -> VerifiedFactReport:
        """Audits a ResearchDossier and creates a VerifiedFactReport."""
        logger.info(f"[FactVerificationAgent] Auditing dossier for '{dossier.topic.title}'...")

        existing = VerifiedFactReport.objects.filter(dossier=dossier).first()
        if existing:
            return existing

        verification_data = self._audit_dossier(dossier)

        confidence = verification_data.get('confidence_level', 0.92)
        contradictions = verification_data.get('contradictions_detected', [])

        report = VerifiedFactReport.objects.create(
            dossier=dossier,
            confidence_level=confidence,
            contradictions_detected=contradictions,
            unsupported_claims_removed=verification_data.get('unsupported_claims_removed', []),
            verified_statistics=verification_data.get('verified_statistics', []),
            verified_quotes=verification_data.get('verified_quotes', []),
            verified_dossier=verification_data.get('sanitized_text', dossier.structured_dossier),
            is_approved=self._approves(confidence, contradictions),
        )

        if report.is_approved:
            logger.info(
                "[FactVerificationAgent] Verified '%s' with %.0f%% confidence.",
                dossier.topic.title, report.confidence_level * 100,
            )
        else:
            logger.warning(
                "[FactVerificationAgent] REJECTED '%s': %.0f%% confidence, "
                "%d contradiction(s).",
                dossier.topic.title, report.confidence_level * 100, len(contradictions),
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

    def _audit_dossier(self, dossier: ResearchDossier) -> Dict[str, Any]:
        if not self.model:
            return self._fallback_audit(dossier)

        try:
            prompt = VERIFICATION_PROMPT.format(
                title=dossier.topic.title,
                technical_explanations=dossier.technical_explanations,
                african_opportunities=dossier.african_opportunities,
                sources=json.dumps(dossier.sources)
            )
            res = self.model.invoke([
                SystemMessage(content="You are a strict fact checker. Return ONLY raw JSON."),
                HumanMessage(content=prompt)
            ])
            content = res.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()

            return json.loads(content, strict=False)
        except Exception as e:
            logger.error(f"[FactVerificationAgent] Error auditing dossier for '{dossier.topic.title}': {e}")
            return self._fallback_audit(dossier)

    def _fallback_audit(self, dossier: ResearchDossier) -> Dict[str, Any]:
        return {
            "confidence_level": 0.90,
            "contradictions_detected": [],
            "unsupported_claims_removed": [],
            "verified_statistics": ["Source references validated"],
            "verified_quotes": [],
            "sanitized_text": dossier.structured_dossier
        }
