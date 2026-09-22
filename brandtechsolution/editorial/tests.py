from unittest.mock import patch

from django.test import TestCase

from trends.models import TrendTopic
from trends.services.intelligence import TrendIntelligenceAgent
from research.services.investigator import ResearchAgent
from research.services.fact_verifier import FactVerificationAgent
from editorial.models import EditorialArticle
from editorial.services.strategy import EditorialStrategyAgent
from editorial.services.writer import AIWriterAgent
from editorial.services.social import MultiPlatformContentAgent
from editorial.services.memory import EditorialMemoryAgent
from editorial.llm_fakes import fake_gemini, unavailable_model
from seo.services.seo_engine import SEOIntelligenceAgent
from media_generation.services.visual_engine import VisualIntelligenceAgent
from approval.services.workflow import HumanApprovalWorkflow
from publishing.services.publisher import PublishingAgent
from brand.models import BlogPost
from research.models import ResearchDossier
from ai_workflows.harness.errors import AgentOutputInvalid, ModelUnavailable


class NewsroomTestCase(TestCase):
    """Shared fixture for the pipeline tests.

    Every test here runs the real agents against a stubbed model. That mattered
    more before step 6 than it does now: each agent used to swallow its own
    exceptions and fall back to a canned draft, so a test passed just as
    readily when the model was unreachable as when it worked -- which is how a
    title long enough to overflow BlogPost.title reached production unnoticed.
    The agents raise now, so an unstubbed test would fail rather than lie; the
    stub is still what keeps the suite off the network and off the quota.
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

    def test_an_unreachable_model_raises_rather_than_scoring(self):
        """The behaviour step 6 deliberately changed.

        This agent used to score the topic from `popularity_score` alone when
        the model was unreachable -- 7.0 business relevance, 7.5 African
        relevance, on everything -- and the result cleared the promotion
        threshold. An outage did not stop the newsroom; it filled it with
        topics nobody had evaluated.
        """
        with unavailable_model():
            with self.assertRaises(ModelUnavailable):
                TrendIntelligenceAgent(priority_threshold=6.0).evaluate_trend(self.topic)

        self.topic.refresh_from_db()
        self.assertEqual(self.topic.status, "discovered")
        self.assertEqual(self.topic.priority_score, 0.0)

    def test_a_declining_agent_leaves_the_topic_for_the_next_cycle(self):
        """An abstention is not a failure, and must not look like a rejection."""
        with fake_gemini({"status": "insufficient_evidence",
                          "notes": "the summary is one sentence"}):
            scored = TrendIntelligenceAgent(priority_threshold=6.0).evaluate_trend(self.topic)

        self.assertIsNone(scored)
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.status, "discovered")


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

    def test_an_unreachable_model_produces_no_draft_at_all(self):
        """The sharpest behaviour change in step 6.

        This used to return a full article assembled from the dossier's own
        sentences, including the hardcoded case study "Representative
        enterprise deployments demonstrate a 40% improvement in performance" --
        a fabricated statistic, in the review queue, indistinguishable from
        reporting. A blank queue is the better failure, and it is the one an
        editor can see.
        """
        with unavailable_model():
            with self.assertRaises(ModelUnavailable):
                ResearchAgent().conduct_research(self.topic)

        self.assertEqual(ResearchDossier.objects.count(), 0)
        self.assertEqual(EditorialArticle.objects.count(), 0)

    def test_a_declining_writer_writes_nothing(self):
        with fake_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)
            report = FactVerificationAgent().verify_dossier(dossier)
            strategy = EditorialStrategyAgent().determine_strategy(report)

        with fake_gemini({"status": "insufficient_evidence",
                          "notes": "the verified report is too thin to write from"}):
            article = AIWriterAgent().write_article(report, strategy)

        self.assertIsNone(article)
        self.assertEqual(EditorialArticle.objects.count(), 0)
        # The topic must not be marked approved_for_article when there is none.
        self.topic.refresh_from_db()
        self.assertNotEqual(self.topic.status, "approved_for_article")

    def test_an_empty_draft_that_validates_is_still_rejected(self):
        """Every content field carries a default so abstention is expressible.

        The cost of that is that `{"status": "ok"}` validates cleanly. This is
        the other half of the guard: an `ok` answer that filled nothing in is a
        failure, not an empty article.
        """
        with fake_gemini():
            dossier = ResearchAgent().conduct_research(self.topic)
            report = FactVerificationAgent().verify_dossier(dossier)
            strategy = EditorialStrategyAgent().determine_strategy(report)

        blanks = {key: "" for key in
                  ("title", "executive_summary", "introduction",
                   "technical_explanation", "conclusion")}
        with fake_gemini(blanks):
            with self.assertRaises(AgentOutputInvalid):
                AIWriterAgent().write_article(report, strategy)

        self.assertEqual(EditorialArticle.objects.count(), 0)


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
        """Guards the stub itself: if the patch target moves, this fails."""
        with fake_gemini() as model:
            ResearchAgent().conduct_research(self.topic)
        self.assertTrue(model.calls, "the research agent did not call the stubbed model")

    def test_a_full_run_never_reaches_the_vendor_library(self):
        """The guard that does not depend on knowing every patch target.

        `fake_gemini` patches one function, which is only correct as long as
        that function is the single door to the network. This closes the door
        itself: both Gemini client classes are replaced with something that
        raises, so any path that slipped past the stub -- chat or, since step 6,
        embeddings -- fails here instead of quietly billing a live call in the
        middle of the suite.
        """
        import langchain_google_genai

        # Recorded rather than raised. A raise is only as good as the shortest
        # except clause between here and the call site, and there is one: the
        # writer catches MemoryUnavailable when remembering a draft, because
        # losing the duplicate-detection entry should not throw away a finished
        # article. A first version of this test raised, hit that handler, and
        # passed while a live embedding call had in fact been made.
        reached = []

        def recorder(*args, **kwargs):
            reached.append(kwargs.get("model") or "unknown")
            raise AssertionError("a test reached the live Gemini client")

        with patch.object(langchain_google_genai, "ChatGoogleGenerativeAI", recorder), \
                patch.object(langchain_google_genai, "GoogleGenerativeAIEmbeddings", recorder):
            article = self.draft_article()
            with fake_gemini():
                MultiPlatformContentAgent().generate_social_ecosystem(article)
            with fake_gemini():
                EditorialMemoryAgent().check_duplicate_coverage(
                    self.topic.title, self.topic.summary,
                )

        self.assertEqual(reached, [], f"live clients were built: {reached}")
        self.assertIsNotNone(article)
