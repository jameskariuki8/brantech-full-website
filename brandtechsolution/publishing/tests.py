"""Publishing an approved article to the live blog."""
from unittest import mock

from django.test import TestCase

from brand.models import BlogPost
from editorial.models import EditorialArticle
from publishing.services.publisher import PublishingAgent


class SlugCollisionTest(TestCase):
    """BlogPost.slug is unique and BlogPost.save() only de-duplicates when the
    slug is blank. The publisher passed article.slug straight into create(),
    so publishing an article whose slug already existed raised IntegrityError.
    With DEBUG on that surfaced in the browser as Django's HTML error page
    failing to parse as JSON, which said nothing about the real cause.
    """

    def setUp(self):
        self.article = EditorialArticle.objects.create(
            title="Same Title", slug="same-title", status="approved",
            executive_summary="Summary",
        )

    def test_publishing_over_an_existing_slug_succeeds(self):
        BlogPost.objects.create(title="Existing", slug="same-title", content="x")

        with mock.patch("editorial.tasks.index_article_embeddings_task"):
            blog_post, _ = PublishingAgent().publish_approved_article(self.article)

        self.assertNotEqual(blog_post.slug, "same-title")
        self.assertTrue(blog_post.slug.startswith("same-title-"))
        self.assertEqual(BlogPost.objects.filter(slug="same-title").count(), 1)

    def test_a_free_slug_is_left_alone(self):
        with mock.patch("editorial.tasks.index_article_embeddings_task"):
            blog_post, _ = PublishingAgent().publish_approved_article(self.article)

        self.assertEqual(blog_post.slug, "same-title")

    def test_repeated_collisions_keep_incrementing(self):
        BlogPost.objects.create(title="A", slug="same-title", content="x")
        BlogPost.objects.create(title="B", slug="same-title-2", content="x")

        with mock.patch("editorial.tasks.index_article_embeddings_task"):
            blog_post, _ = PublishingAgent().publish_approved_article(self.article)

        self.assertEqual(blog_post.slug, "same-title-3")

    def test_the_generated_slug_respects_the_field_length(self):
        long_slug = "x" * 220
        EditorialArticle.objects.filter(pk=self.article.pk).update(slug=long_slug)
        self.article.refresh_from_db()
        BlogPost.objects.create(title="Long", slug=long_slug[:200], content="x")

        with mock.patch("editorial.tasks.index_article_embeddings_task"):
            blog_post, _ = PublishingAgent().publish_approved_article(self.article)

        self.assertLessEqual(len(blog_post.slug), 220)


class EmbeddingHandoffTest(TestCase):
    """Indexing calls the Gemini embedding API. Inline it delayed the editor's
    publish response, and its bare try/except meant a failure was logged as a
    warning and the article silently never reached the vector store."""

    def test_indexing_is_queued_rather_than_run_inline(self):
        article = EditorialArticle.objects.create(
            title="Queued", slug="queued", status="approved",
            executive_summary="Summary",
        )

        with mock.patch("editorial.tasks.index_article_embeddings_task") as task:
            # on_commit, so the worker cannot start before the BlogPost row is
            # visible to its connection. TestCase never commits, so the
            # callbacks have to be executed explicitly.
            with self.captureOnCommitCallbacks(execute=True):
                blog_post, _ = PublishingAgent().publish_approved_article(article)

        task.delay.assert_called_once_with(article.id, blog_post.id)

    def test_publishing_does_not_call_the_embedding_api(self):
        article = EditorialArticle.objects.create(
            title="No API", slug="no-api", status="approved",
            executive_summary="Summary",
        )

        with mock.patch("editorial.tasks.index_article_embeddings_task"), \
             mock.patch("knowledge_base.services.knowledge_graph.KnowledgeBaseAgent") as kb:
            PublishingAgent().publish_approved_article(article)

        kb.assert_not_called()
