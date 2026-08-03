from django.test import TestCase
from trends.models import TrendTopic, CompetitorSource, TrendPrediction
from trends.services.discovery import TrendDiscoveryEngine
from trends.services.intelligence import TrendIntelligenceAgent
from research.models import ResearchDossier, VerifiedFactReport
from research.services.investigator import ResearchAgent
from research.services.fact_verifier import FactVerificationAgent
from editorial.models import EditorialArticle, SocialPackage
from editorial.services.strategy import EditorialStrategyAgent
from editorial.services.writer import AIWriterAgent
from editorial.services.social import MultiPlatformContentAgent
from seo.services.seo_engine import SEOIntelligenceAgent
from media_generation.services.visual_engine import VisualIntelligenceAgent
from approval.services.workflow import HumanApprovalWorkflow
from publishing.services.publisher import PublishingAgent
from brand.models import BlogPost


class AutonomousNewsroomTestCase(TestCase):
    """End-to-end unit and integration tests for Teklora Autonomous AI Newsroom."""

    def setUp(self):
        self.topic = TrendTopic.objects.create(
            title="Autonomous AI Multi-Agent Orchestration",
            summary="A breakdown of modern multi-agent systems and enterprise LLM workflow coordination.",
            source="Hacker News",
            source_url="https://news.ycombinator.com/item?id=1000",
            category="Artificial Intelligence",
            keywords=["AI Agents", "Orchestration", "LangGraph", "Gemini"],
            popularity_score=8.5,
            growth_velocity=9.0,
            status="discovered"
        )

    def test_trend_intelligence_scoring(self):
        agent = TrendIntelligenceAgent(priority_threshold=6.0)
        topic = agent.evaluate_trend(self.topic)
        self.assertGreaterEqual(topic.priority_score, 0.0)
        self.assertIn(topic.status, ['prioritized', 'discovered'])

    def test_research_dossier_synthesis(self):
        agent = ResearchAgent()
        dossier = agent.conduct_research(self.topic)
        self.assertIsNotNone(dossier.id)
        self.assertIn("Autonomous AI", dossier.topic.title)

    def test_fact_verification(self):
        research_agent = ResearchAgent()
        dossier = research_agent.conduct_research(self.topic)
        
        verifier = FactVerificationAgent()
        report = verifier.verify_dossier(dossier)
        self.assertTrue(report.is_approved)
        self.assertGreater(report.confidence_level, 0.0)

    def test_article_drafting_and_publishing_flow(self):
        # Research & Fact-check
        dossier = ResearchAgent().conduct_research(self.topic)
        fact_report = FactVerificationAgent().verify_dossier(dossier)
        
        # Strategy
        strategy = EditorialStrategyAgent().determine_strategy(fact_report)
        
        # Writer
        article = AIWriterAgent().write_article(fact_report, strategy)
        self.assertEqual(article.status, 'review_pending')

        # SEO & Visuals & Social
        SEOIntelligenceAgent().optimize_article(article)
        VisualIntelligenceAgent().generate_visual_package(article)
        social_package = MultiPlatformContentAgent().generate_social_ecosystem(article)
        
        self.assertIsNotNone(social_package.id)
        self.assertIsNotNone(article.hero_image_prompt)

        # Approval & Publishing
        workflow = HumanApprovalWorkflow()
        workflow.approve_article(article)
        self.assertEqual(article.status, 'approved')

        publisher = PublishingAgent()
        blog_post, pub_log = publisher.publish_approved_article(article)
        
        self.assertEqual(article.status, 'published')
        self.assertEqual(blog_post.title, article.title)
        self.assertEqual(BlogPost.objects.filter(pk=blog_post.pk).count(), 1)
