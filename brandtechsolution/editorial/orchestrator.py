"""
Teklora AI Editorial Intelligence Platform - Autonomous Pipeline Orchestrator

Coordinates all 17 specialized AI agents in sequence:
Discovery -> Priority Intelligence -> Research -> Fact Verification -> Strategy -> Writer ->
SEO -> Visual Media -> Multi-Platform -> Human Approval Notification -> Publishing -> Analytics.
"""
import logging
from typing import Dict, Any, List, Optional
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

    def __init__(self, priority_threshold: float = 6.5):
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

    def run_full_autonomous_cycle(self, limit: int = 1, auto_publish: bool = False) -> List[EditorialArticle]:
        """Executes full newsroom pipeline from web discovery to editor notification or publishing."""
        logger.info("================================================================")
        logger.info("🤖 TEKLORA AI EDITORIAL INTELLIGENCE PIPELINE STARTED")
        logger.info("================================================================")

        # Step 1: Discover global trends
        discovered_topics = self.discovery_engine.run_discovery(limit_per_source=5)
        
        # Step 2: Score trends & prioritize high-impact topics
        self.intelligence_agent.evaluate_all_discovered()

        # Step 3: Run competitor gap analysis & predictions
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
                is_dup, reason = self.memory_agent.check_duplicate_coverage(topic.title)
                if is_dup:
                    logger.info(f"Skipping duplicate topic '{topic.title}': {reason}")
                    topic.status = 'rejected'
                    topic.save()
                    continue

                # Step 5: Perform Deep Research Dossier synthesis
                dossier = self.research_agent.conduct_research(topic)

                # Step 6: Fact Verification
                fact_report = self.fact_verifier.verify_dossier(dossier)

                # Step 7: Editorial Strategy & Persona selection
                strategy = self.strategy_agent.determine_strategy(fact_report)

                # Step 8: AI Article Writing
                article = self.writer_agent.write_article(fact_report, strategy)

                # Step 9: SEO Intelligence Optimization
                self.seo_agent.optimize_article(article)

                # Step 10: Visual Media Generation (Hero prompt & SVG infographic)
                self.visual_agent.generate_visual_package(article)

                # Step 11: Multi-Platform Content Generation (LinkedIn, Twitter, Newsletter, etc.)
                self.social_agent.generate_social_ecosystem(article)

                # Step 12: Human Approval Notification
                if auto_publish:
                    self.approval_workflow.approve_article(article, editor_notes="Auto-approved by autonomous policy")
                    self.publisher_agent.publish_approved_article(article)
                else:
                    self.approval_workflow.notify_editors(article)

                processed_articles.append(article)
                logger.info(f"✅ Successfully processed Article #{article.id}: '{article.title}'")

            except Exception as e:
                logger.error(f"Error processing topic '{topic.title}': {e}", exc_info=True)

        logger.info("================================================================")
        logger.info(f"🎉 PIPELINE RUN FINISHED. Processed {len(processed_articles)} articles.")
        logger.info("================================================================")
        return processed_articles
