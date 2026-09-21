"""The fact verification gate, which until now could not refuse anything.

`verify_dossier` hardcoded `is_approved=True`, `VerifiedFactReport.is_approved`
defaults to `True`, and the orchestrator never read the flag -- so a dossier the
agent had itself flagged as self-contradictory was written up and sent for
review exactly like a clean one. The only test touching it asserted a constant.

These tests fail against that behaviour, which is the point of them.
"""
from unittest.mock import patch

from django.test import TestCase

from editorial.llm_fakes import fake_gemini
from editorial.orchestrator import EditorialPipelineOrchestrator
from research.models import ResearchDossier, VerifiedFactReport
from research.services.fact_verifier import MIN_CONFIDENCE, FactVerificationAgent
from research.services.investigator import ResearchAgent
from trends.models import TrendTopic


class VerdictTests(TestCase):
    """The rule itself, in isolation."""

    def test_a_confident_clean_dossier_is_approved(self):
        self.assertTrue(FactVerificationAgent._approves(0.95, []))

    def test_low_confidence_is_refused(self):
        self.assertFalse(FactVerificationAgent._approves(MIN_CONFIDENCE - 0.01, []))

    def test_the_threshold_itself_is_approved(self):
        self.assertTrue(FactVerificationAgent._approves(MIN_CONFIDENCE, []))

    def test_a_contradiction_disqualifies_however_confident(self):
        """The agent has said the dossier disagrees with itself."""
        self.assertFalse(FactVerificationAgent._approves(0.99, ["A contradicts B"]))

    def test_a_non_numeric_confidence_is_not_grounds_to_approve(self):
        self.assertFalse(FactVerificationAgent._approves("very sure", []))
        self.assertFalse(FactVerificationAgent._approves(None, []))


class VerifyDossierTests(TestCase):
    def setUp(self):
        self.topic = TrendTopic.objects.create(
            title="Autonomous AI Multi-Agent Orchestration",
            summary="Multi-agent systems and enterprise LLM workflow coordination.",
            source="Hacker News",
            source_url="https://news.ycombinator.com/item?id=1000",
            category="Artificial Intelligence",
            keywords=["AI Agents"],
            status="discovered",
        )

    def _dossier(self):
        with fake_gemini():
            return ResearchAgent().conduct_research(self.topic)

    def _verify(self, overrides):
        dossier = self._dossier()
        with fake_gemini(overrides):
            return FactVerificationAgent().verify_dossier(dossier)

    def test_a_clean_audit_is_approved(self):
        report = self._verify({"confidence_level": 0.91, "contradictions_detected": []})
        self.assertTrue(report.is_approved)
        self.assertEqual(report.confidence_level, 0.91)

    def test_a_low_confidence_audit_is_refused(self):
        report = self._verify({"confidence_level": 0.2, "contradictions_detected": []})
        self.assertFalse(report.is_approved)

    def test_a_contradiction_is_refused_and_recorded(self):
        report = self._verify({
            "confidence_level": 0.97,
            "contradictions_detected": ["Claims 10x and 2x speedup for the same system"],
        })
        self.assertFalse(report.is_approved)
        self.assertEqual(len(report.contradictions_detected), 1)

    def test_the_verdict_is_not_a_constant(self):
        """The regression this whole file exists for.

        Two audits differing only in what the model said must not produce the
        same verdict. Asserting one approval, as editorial/tests.py did, passes
        against a hardcoded True.
        """
        good = self._verify({"confidence_level": 0.95, "contradictions_detected": []})
        VerifiedFactReport.objects.all().delete()
        ResearchDossier.objects.all().delete()
        bad = self._verify({"confidence_level": 0.95,
                            "contradictions_detected": ["self-contradictory"]})
        self.assertNotEqual(good.is_approved, bad.is_approved)


class PipelineGateTests(TestCase):
    """A refusal has to stop the article, or the gate is still decorative."""

    def setUp(self):
        self.topic = TrendTopic.objects.create(
            title="Autonomous AI Multi-Agent Orchestration",
            summary="Multi-agent systems and enterprise LLM workflow coordination.",
            source="Hacker News",
            source_url="https://news.ycombinator.com/item?id=1000",
            category="Artificial Intelligence",
            keywords=["AI Agents"],
            priority_score=9.0,
            status="prioritized",
        )

    def _run(self, overrides):
        # The orchestrator is constructed INSIDE the patch on purpose. Every
        # agent builds its model client in __init__, so building the
        # orchestrator first hands all fourteen of them a real Gemini client
        # and the stub never applies -- which is exactly what llm_fakes warns
        # about, and what a first version of this test got wrong.
        with fake_gemini(overrides):
            orchestrator = EditorialPipelineOrchestrator()

            # Discovery and scoring reach the network and would re-rank the
            # topic; this test is about what happens after verification, so
            # they are stubbed and the fixture is left prioritised.
            with patch.object(orchestrator.discovery_engine, "run_discovery", return_value=[]), \
                    patch.object(orchestrator.intelligence_agent, "evaluate_all_discovered", return_value=0), \
                    patch.object(orchestrator.competitor_agent, "analyze_competitor_gaps", return_value=None), \
                    patch.object(orchestrator.prediction_agent, "generate_predictions", return_value=None):
                return orchestrator.run_full_autonomous_cycle(limit=1)

    def test_a_rejected_dossier_produces_no_article(self):
        articles = self._run({
            "confidence_level": 0.1,
            "contradictions_detected": ["the dossier disagrees with itself"],
        })

        self.assertEqual(articles, [])
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.status, "rejected")

    def test_an_approved_dossier_still_produces_an_article(self):
        articles = self._run({"confidence_level": 0.95, "contradictions_detected": []})

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].status, "review_pending")
