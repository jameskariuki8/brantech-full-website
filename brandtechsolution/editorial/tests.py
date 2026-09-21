from django.test import TestCase

from trends.models import TrendTopic
from trends.services.intelligence import TrendIntelligenceAgent
from research.services.investigator import ResearchAgent
from research.services.fact_verifier import FactVerificationAgent
from editorial.models import EditorialArticle
from editorial.services.strategy import EditorialStrategyAgent
from editorial.services.writer import AIWriterAgent
from editorial.services.social import MultiPlatformContentAgent
from editorial.llm_fakes import broken_gemini, fake_gemini
from seo.services.seo_engine import SEOIntelligenceAgent
from media_generation.services.visual_engine import VisualIntelligenceAgent
from approval.services.workflow import HumanApprovalWorkflow
from publishing.services.publisher import PublishingAgent
from brand.models import BlogPost


class NewsroomTestCase(TestCase):
    """Shared fixture for the pipeline tests.

    Every test here runs the real agents against a stubbed model. The agents
    each swallow their own exceptions and fall back to a canned draft, so
    without the stub a test passes just as readily when the model is
    unreachable as when it works -- which is how a title long enough to
    overflow BlogPost.title reached production unnoticed.
    """

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
            status="discovered",
        )

    def draft_article(self, overrides=None):
        """Run discovery through drafting, returning the article."""
        with fake_gemini(overrides):
            dossier = ResearchAgent().conduct_research(self.topic)
            report = FactVerificationAgent().verify_dossier(dossier)
            strategy = EditorialStrategyAgent().determine_strategy(report)
            return AIWriterAgent().write_article(report, strategy)


class TrendIntelligenceTests(NewsroomTestCase):
    def test_the_model_scores_are_written_to_the_topic(self):
        with fake_gemini({"novelty_score": 9.5, "african_relevance_score": 8.0}):
            topic = TrendIntelligenceAgent(priority_threshold=6.0).evaluate_trend(self.topic)

        self.assertEqual(topic.novelty_score, 9.5)
        self.assertEqual(topic.african_relevance_score, 8.0)
        self.assertEqual(topic.status, "prioritized")

    def test_a_low_scoring_topic_is_not_prioritised(self):
        low = {key: 1.0 for key in (
            "novelty_score", "business_relevance_score", "african_relevance_score",
            "developer_interest_score", "virality_score", "future_potential",
        )}
        with fake_gemini(low):
            topic = TrendIntelligenceAgent(priority_threshold=6.0).evaluate_trend(self.topic)

        self.assertNotEqual(topic.status, "prioritized")

    def test_an_unreachable_model_falls_back_to_the_heuristic(self):
        with broken_gemini():
            topic = TrendIntelligenceAgent(priority_threshold=6.0).evaluate_trend(self.topic)

        # The point is that it scores the topic anyway rather than raising.
        self.assertGreater(topic.priority_score, 0.0)


class ResearchTests(NewsroomTestCase):
    def test_the_dossier_takes_its_content_from_the_model(self):
        with fake_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)

        self.assertEqual(dossier.topic, self.topic)
        self.assertIn("Agent orchestration", dossier.key_concepts)
        self.assertEqual(dossier.african_opportunities,
                         "Local-language agent tooling for Kenyan fintech.")

    def test_verification_carries_the_audit_onto_the_report(self):
        with fake_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)
            report = FactVerificationAgent().verify_dossier(dossier)

        self.assertTrue(report.is_approved)
        self.assertEqual(report.confidence_level, 0.88)
        self.assertEqual(report.unsupported_claims_removed,
                         ["An unsupported market-size claim."])


class WriterTests(NewsroomTestCase):
    def test_the_draft_uses_the_model_output_and_awaits_review(self):
        article = self.draft_article()

        self.assertEqual(article.title, "Multi-Agent Orchestration in Production")
        self.assertEqual(article.conclusion, "Closing thoughts.")
        self.assertEqual(article.reading_time_minutes, 8)
        # No draft may reach the blog without a human approving it.
        self.assertEqual(article.status, "review_pending")

    def test_a_second_run_reuses_the_existing_draft(self):
        first = self.draft_article()
        with fake_gemini():
            report = first.verification_report
            strategy = EditorialStrategyAgent().determine_strategy(report)
            second = AIWriterAgent().write_article(report, strategy)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(EditorialArticle.objects.count(), 1)

    def test_an_unreachable_model_still_produces_a_reviewable_draft(self):
        with broken_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)
            report = FactVerificationAgent().verify_dossier(dossier)
            strategy = EditorialStrategyAgent().determine_strategy(report)
            article = AIWriterAgent().write_article(report, strategy)

        self.assertEqual(article.status, "review_pending")
        self.assertTrue(article.title)


class PublishingFlowTests(NewsroomTestCase):
    def _publish(self, article):
        HumanApprovalWorkflow().approve_article(article)
        self.assertEqual(article.status, "approved")
        return PublishingAgent().publish_approved_article(article)

    def test_the_full_flow_reaches_a_published_blog_post(self):
        article = self.draft_article()

        with fake_gemini():
            SEOIntelligenceAgent().optimize_article(article)
            VisualIntelligenceAgent().generate_visual_package(article)
            social_package = MultiPlatformContentAgent().generate_social_ecosystem(article)

        self.assertEqual(social_package.linkedin_post, "A LinkedIn post.")
        self.assertIsNotNone(article.hero_image_prompt)

        blog_post, pub_log = self._publish(article)

        self.assertEqual(article.status, "published")
        self.assertEqual(blog_post.title, article.title)
        self.assertEqual(pub_log.blog_post, blog_post)
        self.assertEqual(BlogPost.objects.filter(pk=blog_post.pk).count(), 1)

    def test_an_unapproved_article_is_refused(self):
        article = self.draft_article()
        with self.assertRaises(ValueError):
            PublishingAgent().publish_approved_article(article)

    def test_publishing_twice_updates_the_same_post(self):
        article = self.draft_article()
        blog_post, _ = self._publish(article)
        again, _ = PublishingAgent().publish_approved_article(article)

        self.assertEqual(blog_post.pk, again.pk)
        self.assertEqual(BlogPost.objects.count(), 1)


class LongTitleTests(NewsroomTestCase):
    """EditorialArticle.title holds 300 characters, BlogPost.title holds 200.

    Regression: a generated title in that gap saved fine on the article and
    then raised StringDataRightTruncation at publish, so the editor clicked
    Publish and got a 500 with the article stuck on 'approved'.
    """

    LONG_TITLE = (
        "Autonomous Multi-Agent Orchestration Systems and Their Consequences for "
        "Enterprise Software Architecture, Developer Tooling, Regional Technology "
        "Ecosystems and the Practical Economics of Running Coordinated Language "
        "Model Workflows at Production Scale Across Africa"
    )

    def test_the_fixture_title_is_actually_in_the_dangerous_range(self):
        article_limit = EditorialArticle._meta.get_field("title").max_length
        blog_limit = BlogPost._meta.get_field("title").max_length
        self.assertGreater(len(self.LONG_TITLE), blog_limit)
        self.assertLessEqual(len(self.LONG_TITLE), article_limit)

    def test_an_over_long_title_publishes_instead_of_erroring(self):
        article = self.draft_article({"title": self.LONG_TITLE})
        self.assertEqual(article.title, self.LONG_TITLE)

        HumanApprovalWorkflow().approve_article(article)
        blog_post, _ = PublishingAgent().publish_approved_article(article)

        limit = BlogPost._meta.get_field("title").max_length
        self.assertLessEqual(len(blog_post.title), limit)
        self.assertTrue(self.LONG_TITLE.startswith(blog_post.title))
        self.assertEqual(article.status, "published")

    def test_the_cut_lands_on_a_word_boundary(self):
        fitted = PublishingAgent._fit_title(self.LONG_TITLE)
        self.assertFalse(fitted.endswith(" "))
        # The truncated title should not end mid-word.
        self.assertTrue(self.LONG_TITLE.startswith(fitted + " "))

    def test_a_title_that_already_fits_is_untouched(self):
        self.assertEqual(PublishingAgent._fit_title("A short title"), "A short title")

    def test_a_single_enormous_word_is_still_cut_to_the_limit(self):
        limit = BlogPost._meta.get_field("title").max_length
        fitted = PublishingAgent._fit_title("x" * (limit + 50))
        self.assertEqual(len(fitted), limit)

    def test_republishing_an_over_long_title_also_fits(self):
        """The update branch has its own assignment, and had the same bug."""
        article = self.draft_article({"title": self.LONG_TITLE})
        HumanApprovalWorkflow().approve_article(article)
        PublishingAgent().publish_approved_article(article)

        again, _ = PublishingAgent().publish_approved_article(article)
        limit = BlogPost._meta.get_field("title").max_length
        self.assertLessEqual(len(again.title), limit)


class NoNetworkTests(NewsroomTestCase):
    def test_the_stub_is_what_the_agents_actually_call(self):
        """Guards the stub itself: if a patch target moves, this fails."""
        with fake_gemini() as model:
            ResearchAgent().conduct_research(self.topic)
        self.assertTrue(model.calls, "the research agent did not call the stubbed model")
