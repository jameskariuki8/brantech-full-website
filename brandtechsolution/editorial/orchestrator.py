"""
Teklora AI Editorial Intelligence Platform - Autonomous Pipeline Orchestrator

Coordinates all 17 specialized AI agents in sequence:
Discovery -> Priority Intelligence -> Research -> Fact Verification -> Strategy -> Writer ->
SEO -> Visual Media -> Multi-Platform -> Human Approval Notification -> Publishing -> Analytics.
"""
import logging
from typing import Any, Callable, Dict, List, Optional
from ai_workflows.harness.errors import AgentError
from ai_workflows.harness.steps import StepCache
from trends.services.discovery import TrendDiscoveryEngine
from trends.services.intelligence import TrendIntelligenceAgent
from trends.services.competitor import CompetitorIntelligenceAgent
from trends.services.prediction import TrendPredictionAgent
from trends.models import TrendTopic
from research.services.investigator import ResearchAgent
from research.services.fact_verifier import FactVerificationAgent
from editorial.services.strategy import EditorialStrategyAgent
from editorial.services.writer import AIWriterAgent
from editorial.services.social import MultiPlatformContentAgent
from editorial.services.memory import EditorialMemoryAgent
from editorial.models import EditorialArticle
from seo.services.seo_engine import SEOIntelligenceAgent
from media_generation.services.visual_engine import VisualIntelligenceAgent
from approval.services.workflow import HumanApprovalWorkflow
from publishing.services.publisher import PublishingAgent
from analytics.services.analytics import AnalyticsIntelligenceAgent

logger = logging.getLogger(__name__)


class EditorialPipelineOrchestrator:
    """End-to-end master controller for Teklora's autonomous newsroom."""

    def __init__(self, priority_threshold: float = 6.5, resume: bool = True):
        # `resume` wires up harness/steps.py, which was built for exactly this
        # pipeline and had no callers until now. Eleven stages and several
        # model calls over roughly three minutes: a failure at stage nine used
        # to re-run stages one to eight, paid for again, and every iteration on
        # the failing stage cost another three minutes of waiting.
        #
        # Off for a run that is meant to produce fresh work regardless -- an
        # eval, or a deliberate re-draft. Measuring an agent whose answer came
        # from cache measures the cache.
        self.cache = StepCache(enabled=resume, agent="newsroom")

        self.discovery_engine = TrendDiscoveryEngine()
        self.intelligence_agent = TrendIntelligenceAgent(priority_threshold=priority_threshold)
        self.competitor_agent = CompetitorIntelligenceAgent()
        self.prediction_agent = TrendPredictionAgent()
        self.research_agent = ResearchAgent()
        self.fact_verifier = FactVerificationAgent()
        self.strategy_agent = EditorialStrategyAgent()
        self.writer_agent = AIWriterAgent()
        self.seo_agent = SEOIntelligenceAgent()
        self.visual_agent = VisualIntelligenceAgent()
        self.social_agent = MultiPlatformContentAgent()
        self.approval_workflow = HumanApprovalWorkflow()
        self.publisher_agent = PublishingAgent()
        self.analytics_agent = AnalyticsIntelligenceAgent()
        self.memory_agent = EditorialMemoryAgent()

    def _stage(self, agent, step, inputs, produce):
        """Run a pipeline stage, reusing its row if this is a resume.

        Keyed on the agent's fingerprint as well as the inputs, so editing a
        persona or the stored brand voice invalidates what the old one
        produced. Without that, prompt work would appear to do nothing for a
        day -- which is a genuinely miserable thing to debug.
        """
        return self.cache.remember_row(
            step, inputs, produce, fingerprint=agent.fingerprint(),
        )

    @staticmethod
    def _reject(topic, reason):
        """Mark a topic as not proceeding, and say why in one place."""
        logger.warning("Skipping '%s': %s.", topic.title, reason)
        topic.status = 'rejected'
        topic.save()

    def run_full_autonomous_cycle(
        self,
        limit: int = 1,
        auto_publish: bool = False,
        on_stage: Optional[Callable[[str], None]] = None,
    ) -> List[EditorialArticle]:
        """Executes full newsroom pipeline from web discovery to editor notification or publishing.

        on_stage is called with a stage key from EditorialPipelineRun.STAGES as
        each phase begins. It exists so a Celery task can report progress to
        the dashboard: the run takes minutes, and without it the UI can only
        show an indeterminate spinner. A callback rather than a direct model
        write keeps the orchestrator usable from the management command, where
        there is no run row to update.
        """
        stage = on_stage or (lambda key: None)

        logger.info("================================================================")
        logger.info("🤖 TEKLORA AI EDITORIAL INTELLIGENCE PIPELINE STARTED")
        logger.info("================================================================")

        # Tidied here rather than on a schedule of its own: the work that
        # writes these rows is the obvious place to drop the expired ones, and
        # a cleanup task nobody remembers to run is a table that grows forever.
        dropped = self.cache.prune()
        if dropped:
            logger.info("[steps] dropped %d expired cache entries", dropped)

        # Step 1: Discover global trends
        stage('discovery')
        discovered_topics = self.discovery_engine.run_discovery(limit_per_source=5)

        # Step 2: Score trends & prioritize high-impact topics
        stage('intelligence')
        self.intelligence_agent.evaluate_all_discovered()

        # Step 3: Run competitor gap analysis & predictions
        stage('secondary')
        try:
            self.competitor_agent.analyze_competitor_gaps()
            self.prediction_agent.generate_predictions(timeframe='next_quarter')
        except Exception as e:
            logger.warning(f"Secondary intelligence warning: {e}")

        # Step 4: Pick top prioritized trend topics
        prioritized = TrendTopic.objects.filter(status='prioritized').order_by('-priority_score')[:limit]
        if not prioritized.exists():
            logger.info("No new prioritized trends found matching priority threshold.")
            return []

        processed_articles = []
        for topic in prioritized:
            try:
                # Check memory for duplicates
                is_dup, reason = self.memory_agent.check_duplicate_coverage(
                    topic.title, topic.summary,
                )
                if is_dup:
                    logger.info("Skipping duplicate topic '%s': %s", topic.title, reason)
                    topic.status = 'rejected'
                    topic.save()
                    continue

                # Step 5: Perform Deep Research Dossier synthesis
                #
                # Every stage below can now decline. Before step 6 none of them
                # could: each caught its own exception and returned a canned
                # object, so the pipeline ran to completion whether or not any
                # work had been done. A None here means the agent said it could
                # not do the job, and the honest response is to stop this topic
                # rather than hand the next stage something to pretend with.
                stage('research')
                dossier = self._stage(
                    self.research_agent, 'research', {'topic': topic.id},
                    lambda: self.research_agent.conduct_research(topic),
                )
                if dossier is None:
                    self._reject(topic, "research produced no dossier")
                    continue

                # Step 6: Fact Verification
                stage('verification')
                fact_report = self._stage(
                    self.fact_verifier, 'verification', {'dossier': dossier.id},
                    lambda: self.fact_verifier.verify_dossier(dossier),
                )

                # Honour the verdict. The verifier used to hardcode
                # is_approved=True and nothing read the flag, so a dossier it
                # had flagged as self-contradictory was written up and sent for
                # review exactly like a clean one. Rejection skips the topic
                # rather than failing the run: the other prioritised topics in
                # this cycle are unaffected, and the same rejection path the
                # duplicate check above already uses applies here.
                if not fact_report.is_approved:
                    logger.warning(
                        "Skipping '%s': fact verification rejected the dossier "
                        "(%.0f%% confidence, %d contradiction(s)).",
                        topic.title,
                        fact_report.confidence_level * 100,
                        len(fact_report.contradictions_detected),
                    )
                    topic.status = 'rejected'
                    topic.save()
                    continue

                # Step 7: Editorial Strategy & Persona selection
                #
                # Not cached, and it is the one stage here that should not be:
                # it makes no model call at all, just branches on the topic's
                # category. Caching free work would add a database round trip
                # to save nothing.
                stage('strategy')
                strategy = self.strategy_agent.determine_strategy(fact_report)

                # Step 8: AI Article Writing
                stage('writing')
                article = self._stage(
                    self.writer_agent, 'writing',
                    {'report': fact_report.id, 'strategy': strategy.get('profile_key', '')},
                    lambda: self.writer_agent.write_article(fact_report, strategy),
                )
                if article is None:
                    self._reject(topic, "the writer declined to draft it")
                    continue

                # Step 9: SEO Intelligence Optimization
                stage('seo')
                self.seo_agent.optimize_article(article)

                # Step 10: Visual Media Generation (Hero prompt & SVG infographic)
                stage('visual')
                self.visual_agent.generate_visual_package(article)

                # Step 11: Multi-Platform Content Generation (LinkedIn, Twitter, Newsletter, etc.)
                #
                # The only stage whose failure is not fatal to the topic. The
                # article is written, verified and reviewable; the package is
                # downstream of it and can be regenerated on its own, so losing
                # it should not discard the piece.
                stage('social')
                if self.social_agent.generate_social_ecosystem(article) is None:
                    logger.warning(
                        "No social package for '%s'; the article still goes to review.",
                        article.title,
                    )

                # Step 12: Human Approval Notification
                stage('handoff')
                if auto_publish:
                    self.approval_workflow.approve_article(article, editor_notes="Auto-approved by autonomous policy")
                    self.publisher_agent.publish_approved_article(article)
                else:
                    self.approval_workflow.notify_editors(article)

                processed_articles.append(article)
                logger.info(f"✅ Successfully processed Article #{article.id}: '{article.title}'")

            except AgentError as e:
                # An agent failed rather than declined. It has already recorded
                # its own health and alerted; this is the pipeline deciding
                # what to do about it, which is to lose the topic and keep the
                # cycle. Left `discovered`-adjacent rather than `rejected`: the
                # topic was never judged, and marking it rejected would bury it.
                logger.error("Agent failure on topic '%s': %s", topic.title, e)
            except Exception as e:
                logger.error(f"Error processing topic '{topic.title}': {e}", exc_info=True)

        logger.info("================================================================")
        logger.info(f"🎉 PIPELINE RUN FINISHED. Processed {len(processed_articles)} articles.")
        logger.info("================================================================")
        return processed_articles
