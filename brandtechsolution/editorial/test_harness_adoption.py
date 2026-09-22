"""Step 6: the newsroom on the harness.

Six agents lost their own model clients, their own JSON parsers and -- the part
that changes behaviour -- their own fallbacks. These tests are about what that
bought and what it cost, not about the plumbing: the plumbing is covered by
ai_workflows/test_harness.py, and the agents' ordinary output by editorial/tests.py.
"""
import math
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import TestCase

from ai_workflows.harness.alerts import ALERT_CAPABILITY
from ai_workflows.harness.base import AgentRequest
from ai_workflows.harness.errors import MemoryUnavailable, ModelUnavailable
from ai_workflows.models import AgentHealth, AgentProfile
from editorial.llm_fakes import fake_gemini, unavailable_model
from editorial.models import EditorialArticle
from editorial.services.memory import DUPLICATE_SIMILARITY, EditorialMemoryAgent
from editorial.services.social import MultiPlatformContentAgent
from editorial.services.writer import AIWriterAgent
from research.models import ResearchDossier, VerifiedFactReport
from research.services.fact_verifier import FactVerificationAgent
from research.services.investigator import ResearchAgent
from trends.models import TrendPrediction, TrendTopic
from trends.services.intelligence import TrendIntelligenceAgent
from trends.services.prediction import TrendPredictionAgent

AGENTS = [
    TrendIntelligenceAgent, TrendPredictionAgent, ResearchAgent,
    FactVerificationAgent, AIWriterAgent, MultiPlatformContentAgent,
]


def _topic(title="Autonomous AI Multi-Agent Orchestration", **kwargs):
    return TrendTopic.objects.create(
        title=title,
        summary=kwargs.pop("summary", "Multi-agent systems and enterprise LLM coordination."),
        source="Hacker News",
        source_url="https://news.ycombinator.com/item?id=1000",
        category="Artificial Intelligence",
        keywords=["AI Agents"],
        **kwargs,
    )


class DeclarationTests(TestCase):
    """What each agent now says about itself, in one place."""

    def test_every_newsroom_agent_declares_a_persona(self):
        for agent_class in AGENTS:
            with self.subTest(agent=agent_class.__name__):
                self.assertIsNotNone(agent_class.persona)
                self.assertTrue(agent_class.persona.role)

    def test_the_personas_are_actually_different_agents(self):
        """Six copies of one persona would be a rename, not a design."""
        roles = {a.persona.role for a in AGENTS}
        self.assertEqual(len(roles), len(AGENTS))

    def test_every_persona_states_what_it_must_not_do(self):
        """The negative space is the half that stops fabrication.

        Every one of these agents had a fallback that invented content. A
        persona that only describes ambition reproduces that in prose.
        """
        for agent_class in AGENTS:
            with self.subTest(agent=agent_class.__name__):
                self.assertTrue(agent_class.persona.constraints)

    def test_no_fallback_survives_on_any_agent(self):
        """The regression guard for the whole step.

        Named for the shape rather than the exact method names, so a
        reintroduced fallback under a new name is still caught.
        """
        for agent_class in AGENTS:
            leftovers = [
                name for name in dir(agent_class)
                if ("fallback" in name.lower() or "heuristic" in name.lower())
                # `allow_fallback` is the harness flag for failing over to
                # another *model*, which is a different thing wearing the same
                # word. Worth the explicit exclusion rather than a looser
                # pattern, because the collision will catch a reader out.
                and name != "allow_fallback"
            ]
            self.assertEqual(leftovers, [], f"{agent_class.__name__}: {leftovers}")

    def test_an_agent_can_be_constructed_without_a_credential(self):
        """They used to build a live client in __init__.

        That is why `research/test_verification_gate.py` has to construct the
        orchestrator inside the patch, and why a first version of that test
        made a 149-second live API call before failing. Resolution is lazy now.
        """
        with unavailable_model():
            for agent_class in AGENTS:
                with self.subTest(agent=agent_class.__name__):
                    self.assertTrue(agent_class().name)

    def test_the_verifier_does_not_fail_over_between_models(self):
        """Its verdicts are compared across eval runs; a silent model swap
        mid-comparison would make a change in score unattributable."""
        self.assertFalse(FactVerificationAgent.allow_fallback)


class BrandVoiceTests(TestCase):
    def test_the_persona_speaks_in_the_stored_voice(self):
        profile = AgentProfile.load()
        profile.brand_voice = "Terse, sceptical, and allergic to adjectives."
        profile.save()

        rendered = AIWriterAgent().voiced_persona().render()
        self.assertIn("allergic to adjectives", rendered)

    def test_every_agent_speaks_in_the_same_voice(self):
        """The drift this replaces: EditorialMemory.brand_voice was read only
        by the writer, while the chat assistant carried its own hardcoded copy."""
        profile = AgentProfile.load()
        profile.brand_voice = "One voice."
        profile.save()

        voices = {a().voiced_persona().voice for a in AGENTS}
        self.assertEqual(voices, {"One voice."})


class HealthWiringTests(TestCase):
    """Step 5 built the alerting; this is the wire to it."""

    def setUp(self):
        user = User.objects.create_user("ops", email="ops@example.com", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename=ALERT_CAPABILITY))
        self.topic = _topic()

    def test_a_failing_agent_pages_somebody(self):
        with unavailable_model():
            with self.assertRaises(ModelUnavailable):
                ResearchAgent().conduct_research(self.topic)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("research is failing", mail.outbox[0].subject)
        self.assertTrue(AgentHealth.objects.get(agent="research").is_failing)

    def test_recovery_is_recorded_and_announced(self):
        with unavailable_model():
            with self.assertRaises(ModelUnavailable):
                ResearchAgent().conduct_research(self.topic)
        mail.outbox.clear()

        with fake_gemini():
            ResearchAgent().conduct_research(self.topic)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("working again", mail.outbox[0].subject)
        self.assertFalse(AgentHealth.objects.get(agent="research").is_failing)

    def test_an_abstention_is_not_an_outage(self):
        """An agent declining because the evidence is thin is working correctly.

        Paging on it would teach the recipients to ignore the alerts, which is
        the one failure mode that would undo step 5 entirely.
        """
        with fake_gemini({"status": "insufficient_evidence", "notes": "nothing to go on"}):
            self.assertIsNone(ResearchAgent().conduct_research(self.topic))

        self.assertEqual(mail.outbox, [])
        self.assertFalse(
            AgentHealth.objects.filter(agent="research", status=AgentHealth.FAILING).exists()
        )


class AbstentionTests(TestCase):
    """A schema that permits "I could not determine this", and callers that route on it."""

    def setUp(self):
        self.topic = _topic(status="prioritized", priority_score=9.0)

    def _dossier(self):
        with fake_gemini():
            return ResearchAgent().conduct_research(self.topic)

    def test_a_declining_verifier_records_a_refusal_rather_than_nothing(self):
        """The refusal is a verdict and belongs in the record.

        An editor looking at the topic can then see it was considered and where
        it stopped, instead of finding a topic with no report and no trace.
        """
        dossier = self._dossier()
        with fake_gemini({"status": "insufficient_evidence",
                          "notes": "the dossier cites nothing checkable"}):
            report = FactVerificationAgent().verify_dossier(dossier)

        self.assertFalse(report.is_approved)
        self.assertEqual(report.confidence_level, 0.0)
        self.assertEqual(VerifiedFactReport.objects.count(), 1)

    def test_a_declining_verifier_does_not_present_the_dossier_as_audited(self):
        dossier = self._dossier()
        with fake_gemini({"status": "refused", "notes": "out of scope"}):
            report = FactVerificationAgent().verify_dossier(dossier)

        self.assertEqual(report.verified_statistics, [])
        self.assertEqual(report.unsupported_claims_removed, [])
        self.assertFalse(report.is_approved)

    def test_forecasts_come_back_wrapped_so_none_is_expressible(self):
        """The prompt used to ask for a bare JSON list.

        A top-level array has nowhere to put a status, so a forecaster with
        nothing to forecast could not say so -- and would produce three.
        """
        _topic(title="Some other trend")
        with fake_gemini({"status": "insufficient_evidence", "notes": "no usable signal"}):
            predictions = TrendPredictionAgent().generate_predictions()

        self.assertEqual(predictions, [])
        self.assertEqual(TrendPrediction.objects.count(), 0)

    def test_a_forecast_missing_half_its_content_is_dropped(self):
        _topic(title="Some other trend")
        with fake_gemini({"predictions": [
            {"topic_name": "A real forecast", "prediction_report": "Why."},
            {"topic_name": "", "prediction_report": "An orphaned report."},
        ]}):
            predictions = TrendPredictionAgent().generate_predictions()

        self.assertEqual(len(predictions), 1)
        self.assertEqual(predictions[0].topic_name, "A real forecast")

    def test_nothing_to_forecast_from_is_not_forecast_from_placeholders(self):
        """It used to substitute three hardcoded topic names and forecast from
        those, producing an invented forecast that read like a real one."""
        TrendTopic.objects.all().delete()
        with fake_gemini() as model:
            self.assertEqual(TrendPredictionAgent().generate_predictions(), [])
        self.assertEqual(model.calls, [])


class OrchestratorRoutingTests(TestCase):
    """Each abstention has to stop the right amount of the pipeline."""

    def setUp(self):
        self.topic = _topic(status="prioritized", priority_score=9.0)

    def _run(self, **stub):
        from editorial.orchestrator import EditorialPipelineOrchestrator

        with fake_gemini(stub or None):
            orchestrator = EditorialPipelineOrchestrator()
            with patch.object(orchestrator.discovery_engine, "run_discovery", return_value=[]), \
                    patch.object(orchestrator.intelligence_agent, "evaluate_all_discovered", return_value=0), \
                    patch.object(orchestrator.competitor_agent, "analyze_competitor_gaps", return_value=None), \
                    patch.object(orchestrator.prediction_agent, "generate_predictions", return_value=[]):
                return orchestrator.run_full_autonomous_cycle(limit=1)

    def test_research_declining_rejects_the_topic_and_writes_nothing(self):
        articles = self._run(status="insufficient_evidence", notes="nothing to research")

        self.assertEqual(articles, [])
        self.assertEqual(ResearchDossier.objects.count(), 0)
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.status, "rejected")

    def test_a_social_failure_does_not_discard_the_article(self):
        """The only stage whose abstention is not fatal.

        The article is written, verified and reviewable; the package is
        downstream of it and can be regenerated on its own.
        """
        from editorial.orchestrator import EditorialPipelineOrchestrator

        with fake_gemini():
            orchestrator = EditorialPipelineOrchestrator()
            with patch.object(orchestrator.discovery_engine, "run_discovery", return_value=[]), \
                    patch.object(orchestrator.intelligence_agent, "evaluate_all_discovered", return_value=0), \
                    patch.object(orchestrator.competitor_agent, "analyze_competitor_gaps", return_value=None), \
                    patch.object(orchestrator.prediction_agent, "generate_predictions", return_value=[]), \
                    patch.object(orchestrator.social_agent, "generate_social_ecosystem", return_value=None):
                articles = orchestrator.run_full_autonomous_cycle(limit=1)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].status, "review_pending")

    def test_an_agent_failure_loses_the_topic_not_the_cycle(self):
        from editorial.llm_fakes import fake_embeddings
        from editorial.orchestrator import EditorialPipelineOrchestrator

        # Embeddings stubbed but chat unavailable, so the failure lands on the
        # research agent rather than on the duplicate check. Nesting
        # `unavailable_model` inside `fake_gemini` would not work: they patch
        # the same name, and the inner one wins.
        with fake_embeddings(), unavailable_model():
            orchestrator = EditorialPipelineOrchestrator()
            with patch.object(orchestrator.discovery_engine, "run_discovery", return_value=[]), \
                    patch.object(orchestrator.intelligence_agent, "evaluate_all_discovered", return_value=0), \
                    patch.object(orchestrator.competitor_agent, "analyze_competitor_gaps", return_value=None), \
                    patch.object(orchestrator.prediction_agent, "generate_predictions", return_value=[]):
                articles = orchestrator.run_full_autonomous_cycle(limit=1)

        self.assertEqual(articles, [])
        self.assertEqual(EditorialArticle.objects.count(), 0)
        self.topic.refresh_from_db()
        # Not 'rejected': the topic was never judged, and marking it rejected
        # would bury a topic that failed for reasons of ours, not of its own.
        self.assertNotEqual(self.topic.status, "rejected")


class PinnedEmbedder:
    """Returns a stated vector per text, so a test can pin similarity exactly.

    The bag-of-words fake in llm_fakes keeps the suite offline, but it has no
    sense of paraphrase -- leaning on it to decide whether two differently
    worded headlines are the same story would test its hashing rather than the
    threshold.

    The first text embeds to the first axis; every other text embeds to a
    vector at a stated cosine from it, which is what `recall` reports as the
    score.
    """

    def __init__(self, similarities, dimensions=3072):
        self.similarities = similarities
        self.dimensions = dimensions

    def embed_query(self, text):
        vector = [0.0] * self.dimensions
        similarity = 1.0
        for needle, value in self.similarities.items():
            if needle.lower() in (text or "").lower():
                similarity = value
                break
        vector[0] = similarity
        vector[1] = math.sqrt(max(0.0, 1.0 - similarity ** 2))
        return vector

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]


class DuplicateCoverageTests(TestCase):
    """The substring check, and the semantic one now behind it."""

    def setUp(self):
        self.agent = EditorialMemoryAgent()

    def _remember_article(self, title, embedder):
        topic = _topic(title=title)
        article = EditorialArticle.objects.create(
            topic=topic, title=title, subtitle="", executive_summary="A summary.",
            hero_paragraph="", introduction="", problem_statement="",
            current_developments="", technical_explanation="", industry_impact="",
            african_perspective="", future_predictions="", conclusion="",
            meta_description="A summary.",
        )
        with patch("ai_workflows.harness.llm.get_embedder", return_value=embedder):
            AIWriterAgent._remember(article)
        return article

    def test_the_substring_check_still_catches_a_literal_republish(self):
        self._remember_article("Autonomous AI Multi-Agent Orchestration",
                               PinnedEmbedder({}))
        is_dup, reason = self.agent.check_duplicate_coverage(
            "Autonomous AI Multi-Agent Orchestration Reaches Production"
        )
        self.assertTrue(is_dup)
        self.assertIn("Title overlaps", reason)

    def test_a_reworded_headline_is_caught_semantically(self):
        """What `title__icontains=title[:20]` could not do.

        "OpenAI Ships GPT-5 Agents" and "GPT-5's Agent Mode, Explained" share
        no 20-character prefix, so both would have been researched, written and
        queued as separate stories.
        """
        embedder = PinnedEmbedder({"agent mode": 0.95})
        self._remember_article("OpenAI Ships GPT-5 Agents", embedder)

        with patch("ai_workflows.harness.llm.get_embedder", return_value=embedder):
            is_dup, reason = self.agent.check_duplicate_coverage(
                "GPT-5's Agent Mode, Explained", "A look at the new agent mode."
            )

        self.assertTrue(is_dup)
        self.assertIn("Semantically matches", reason)

    def test_a_genuinely_different_story_is_not_a_duplicate(self):
        """A dedup that refuses everything is as useless as one that refuses
        nothing, and only the pair shows the threshold is actually applied."""
        embedder = PinnedEmbedder({"quantum": 0.30})
        self._remember_article("OpenAI Ships GPT-5 Agents", embedder)

        with patch("ai_workflows.harness.llm.get_embedder", return_value=embedder):
            is_dup, _ = self.agent.check_duplicate_coverage(
                "Quantum-Safe Cryptography Lands in OpenSSL", "Post-quantum defaults."
            )

        self.assertFalse(is_dup)

    def test_the_threshold_is_the_boundary_it_claims_to_be(self):
        embedder = PinnedEmbedder({"just under": DUPLICATE_SIMILARITY - 0.01})
        self._remember_article("OpenAI Ships GPT-5 Agents", embedder)

        with patch("ai_workflows.harness.llm.get_embedder", return_value=embedder):
            is_dup, _ = self.agent.check_duplicate_coverage("Just under the line", "")

        self.assertFalse(is_dup)

    def test_nothing_remembered_yet_is_not_a_duplicate(self):
        with patch("ai_workflows.harness.llm.get_embedder",
                   return_value=PinnedEmbedder({})):
            is_dup, reason = self.agent.check_duplicate_coverage("A brand new story", "")

        self.assertFalse(is_dup)
        self.assertEqual(reason, "Topic is original")

    def test_a_check_that_cannot_run_raises_rather_than_passing(self):
        """A check that silently stops checking is worse than no check.

        The pipeline would go on reporting that it had looked, and publish the
        duplicate this exists to prevent.
        """
        def no_embedder(*args, **kwargs):
            raise ModelUnavailable("no key")

        with patch("ai_workflows.harness.llm.get_embedder", new=no_embedder):
            with self.assertRaises(MemoryUnavailable):
                self.agent.check_duplicate_coverage("A brand new story", "")


class RememberingTests(TestCase):
    def setUp(self):
        self.topic = _topic()

    def test_a_draft_is_remembered_so_the_next_cycle_sees_it(self):
        from knowledge_base.models import MemoryDocument

        with fake_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)
            report = FactVerificationAgent().verify_dossier(dossier)
            article = AIWriterAgent().write_article(report, {})

        self.assertTrue(
            MemoryDocument.objects.filter(kind="article", title=article.title).exists()
        )

    def test_losing_memory_does_not_lose_the_article(self):
        """Deliberately not fatal, and deliberately not silent.

        The article is written and correct; what is lost is that the next cycle
        may not recognise the topic as covered. Failing the draft over it would
        throw away good work to protect against a duplicate.
        """
        def no_embedder(*args, **kwargs):
            raise ModelUnavailable("no key")

        with fake_gemini(embeddings=False):
            with patch("ai_workflows.harness.llm.get_embedder", new=no_embedder):
                dossier = ResearchAgent().conduct_research(self.topic)
                report = FactVerificationAgent().verify_dossier(dossier)
                with self.assertLogs("editorial.services.writer", level="ERROR"):
                    article = AIWriterAgent().write_article(report, {})

        self.assertIsNotNone(article)
        self.assertEqual(article.status, "review_pending")


class StructuredOutputTests(TestCase):
    """Native structure where the provider has it, the parser where it does not."""

    def setUp(self):
        self.topic = _topic()

    def test_the_native_path_produces_the_same_dossier_as_the_text_path(self):
        with fake_gemini(structured=True):
            native = ResearchAgent().conduct_research(self.topic)

        ResearchDossier.objects.all().delete()
        with fake_gemini(structured=False):
            parsed = ResearchAgent().conduct_research(_topic(title="A second topic"))

        self.assertEqual(native.technical_explanations, parsed.technical_explanations)
        self.assertEqual(native.sources, parsed.sources)

    def test_a_fenced_response_is_still_understood(self):
        """One fence-strip, where there used to be six copies of it."""
        with fake_gemini(structured=False) as model:
            original = model.invoke
            model.invoke = lambda messages, *a, **k: _fenced(original(messages))
            dossier = ResearchAgent().conduct_research(self.topic)

        self.assertEqual(dossier.technical_explanations,
                         "Agents coordinate through a shared message graph.")


def _fenced(response):
    response.content = f"```json\n{response.content}\n```"
    return response


class MemoryHealthTests(TestCase):
    """The dedup check is not an Agent, but it can still halt the newsroom."""

    def setUp(self):
        user = User.objects.create_user("ops", email="ops@example.com", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename=ALERT_CAPABILITY))

    def test_a_broken_duplicate_check_pages_somebody(self):
        """Without this, a dead embedding provider stops every topic in the
        cycle behind nothing but a log line."""
        def no_embedder(*args, **kwargs):
            raise ModelUnavailable("no key")

        with patch("ai_workflows.harness.llm.get_embedder", new=no_embedder):
            with self.assertRaises(MemoryUnavailable):
                EditorialMemoryAgent().check_duplicate_coverage("A story", "")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("editorial_memory is failing", mail.outbox[0].subject)

    def test_a_working_check_says_nothing(self):
        with patch("ai_workflows.harness.llm.get_embedder",
                   return_value=PinnedEmbedder({})):
            EditorialMemoryAgent().check_duplicate_coverage("A story", "")

        self.assertEqual(mail.outbox, [])


class VerificationEvidenceTests(TestCase):
    """Step 9: the verifier checks claims against something outside itself.

    Until now it asked a language model whether it believed itself, which is a
    strange thing for a fact checker to do.
    """

    def setUp(self):
        self.topic = _topic()

    def _report(self, evidence="[fetch_url(url='https://example.com/a')]\nThe source says X."):
        with fake_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)
            with patch.object(FactVerificationAgent, "gather_evidence",
                              return_value=evidence):
                return FactVerificationAgent().verify_dossier(dossier)

    def test_the_evidence_is_recorded_against_the_verdict(self):
        """A verdict whose evidence is not recorded is a verdict nobody can
        review, and being reviewable is this agent's whole purpose."""
        report = self._report()
        self.assertIn("The source says X.", report.verification_evidence)

    def test_the_evidence_does_not_reach_the_field_the_writer_drafts_from(self):
        """The bug this field exists to avoid.

        Appending the transcript to `verified_dossier` would put fetched page
        text -- and its numbers -- into the article prompt, past the
        sanitisation that had just removed unsupported claims. It would also
        reach the eval that looks for invented figures and read as the verifier
        inventing them.
        """
        report = self._report()
        self.assertNotIn("fetch_url", report.verified_dossier)
        self.assertNotIn("The source says X.", report.verified_dossier)

    def test_a_refusal_still_records_what_was_checked(self):
        with fake_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)

        with patch.object(FactVerificationAgent, "gather_evidence",
                          return_value="Could not reach the cited source."):
            with fake_gemini({"status": "insufficient_evidence",
                              "notes": "sources unreachable"}):
                report = FactVerificationAgent().verify_dossier(dossier)

        self.assertFalse(report.is_approved)
        self.assertIn("Could not reach", report.verification_evidence)

    def test_the_verifier_actually_asks_for_its_tools(self):
        """Guards the wiring: an agent with a suite that never gathers has
        tools on paper only."""
        with fake_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)
            with patch.object(FactVerificationAgent, "gather_evidence",
                              return_value="") as gather:
                FactVerificationAgent().verify_dossier(dossier)

        gather.assert_called_once()
        self.assertIn(self.topic.title, gather.call_args[0][0])

    def test_no_evidence_leaves_the_prompt_unchanged(self):
        """An agent with no tools must not be handed an empty evidence header
        that reads as "you checked and found nothing"."""
        from research.services.fact_verifier import VERIFICATION_PROMPT

        rendered = VERIFICATION_PROMPT.format(
            title="T", technical_explanations="E", african_opportunities="A",
            sources="[]", evidence="",
        )
        self.assertNotIn("What you found", rendered)


THIN = (
    "Multi-agent orchestration frameworks coordinate several model calls. The "
    "verifier could not confirm adoption figures or performance benchmarks."
)


def _verified_report(body, *, title="Unbenchmarked orchestration"):
    """A report with a controlled body, built directly.

    Not by running the verifier: these tests are about what the *writer* does
    with a given report, and letting the verifier produce it would make the
    input vary.
    """
    dossier = ResearchDossier.objects.create(
        topic=_topic(title=title),
        key_concepts=["Orchestration"],
        timeline=[],
        technical_explanations=body,
        advantages_and_limitations={},
        african_opportunities="Local teams are evaluating the approach.",
        sources=[],
        structured_dossier=body,
    )
    return VerifiedFactReport.objects.create(
        dossier=dossier,
        confidence_level=0.9,
        contradictions_detected=[],
        unsupported_claims_removed=[],
        verified_statistics=[],
        verified_quotes=[],
        verified_dossier=body,
        is_approved=True,
    )


class InventedFiguresTests(TestCase):
    """The writer is checked against its evidence, not asked nicely.

    Its persona has forbidden inventing statistics since step 6. A live eval
    run caught it writing "2%" into an article whose verified report says in
    as many words that no benchmark could be confirmed. An instruction in a
    prompt is a request, so this is the check that follows it.
    """

    def _write(self, report):
        """Draft, with the continuity lookup stubbed out.

        That step has its own tests, and leaving it live here would put the
        fake's whole payload into the prompt and into the call count.
        """
        with patch.object(AIWriterAgent, "gather_evidence", return_value=""):
            return AIWriterAgent().write_article(
                report, {"target_audience": "developers"},
            )

    def test_a_clean_draft_is_left_alone(self):
        """One call, no second-guessing, when nothing was invented."""
        report = _verified_report(THIN)

        with fake_gemini({"case_studies": "No deployment has published figures."}) as model:
            article = self._write(report)

        self.assertIsNotNone(article)
        self.assertEqual(len(model.calls), 1)

    def test_an_invented_figure_is_sent_back_once(self):
        report = _verified_report(THIN)

        with fake_gemini({"case_studies": "Deployments report a 40% improvement."}) as model:
            self._write(report)

        self.assertEqual(len(model.calls), 2)
        self.assertIn("40%", str(model.calls[1]))

    def test_a_figure_the_report_supports_survives(self):
        """A writer that strips every number is as useless as one that invents
        them, and only the pair shows the difference is drawn on the evidence
        rather than on a blanket rule."""
        report = _verified_report(
            "One published benchmark reports a 35% reduction in latency."
        )

        with fake_gemini({"case_studies": "The benchmark showed a 35% reduction."}) as model:
            article = self._write(report)

        self.assertIsNotNone(article)
        self.assertEqual(len(model.calls), 1)

    def test_it_declines_rather_than_shipping_the_figure_twice(self):
        """A false article is worse than no article -- the whole lesson of the
        fallback draft this agent replaced.

        The fake answers the same way both times, which is the case that
        matters: a model that will not stop inventing the figure must not get
        its article published anyway.
        """
        report = _verified_report(THIN)

        with fake_gemini({"case_studies": "Deployments report a 40% improvement."}):
            article = self._write(report)

        self.assertIsNone(article)
        self.assertFalse(EditorialArticle.objects.exists())

    def test_a_figure_anywhere_in_the_draft_counts(self):
        """Not only in the sections somebody remembered to list."""
        report = _verified_report(THIN)

        with fake_gemini({"meta_description": "Adoption grew 3x last year."}) as model:
            self._write(report)

        self.assertEqual(len(model.calls), 2)

    def test_the_refusal_says_which_figures_and_why(self):
        """An editor seeing no article needs to know it was a decision."""
        report = _verified_report(THIN)

        with fake_gemini({"case_studies": "Deployments report a 40% improvement."}):
            with patch.object(AIWriterAgent, "gather_evidence", return_value=""):
                result = AIWriterAgent().execute(AgentRequest(
                    payload={"report": report, "strategy": {}},
                ))

        self.assertTrue(result.abstained)
        self.assertIn("40%", result.notes)

    def test_continuity_evidence_cannot_launder_a_figure(self):
        """The brief that gathers it says it is not source material. A number
        from a past article counting as support here is exactly how a claim the
        verifier removed gets back in."""
        from editorial.services.writer import _sources_text

        self.assertNotIn("40%", _sources_text(_verified_report(THIN)))
