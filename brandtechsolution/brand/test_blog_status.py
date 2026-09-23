from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase

from brand.models import BlogPost


def staff_with(*codenames):
    user = User.objects.create_user("cap", password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class BlogStatusModelTest(TestCase):
    def test_new_posts_default_to_draft(self):
        post = BlogPost.objects.create(
            title="t", content="c", excerpt="e", category="cat"
        )
        self.assertEqual(post.status, "draft")


class PublicBlogVisibilityTest(TestCase):
    def setUp(self):
        self.draft = BlogPost.objects.create(
            title="Draft post", content="c", excerpt="e", category="cat",
            status="draft",
        )
        self.live = BlogPost.objects.create(
            title="Live post", content="c", excerpt="e", category="cat",
            status="published",
        )

    def test_blog_list_hides_drafts(self):
        resp = self.client.get("/blog/")
        self.assertContains(resp, "Live post")
        self.assertNotContains(resp, "Draft post")

    def test_blog_detail_404s_for_a_draft(self):
        resp = self.client.get(f"/blog/{self.draft.slug}/")
        self.assertEqual(resp.status_code, 404)

    def test_blog_detail_serves_a_published_post(self):
        resp = self.client.get(f"/blog/{self.live.slug}/")
        self.assertEqual(resp.status_code, 200)


class PublishCapabilityTest(TestCase):
    def setUp(self):
        self.post = BlogPost.objects.create(
            title="t", content="c", excerpt="e", category="cat", status="draft"
        )

    def test_manage_blog_alone_cannot_publish(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            f"/api/posts/{self.post.pk}/",
            {"title": "t", "content": "c", "excerpt": "e",
             "category": "cat", "status": "published"},
        )
        self.assertEqual(resp.status_code, 403)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, "draft")

    def test_manage_blog_can_still_edit_a_draft(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            f"/api/posts/{self.post.pk}/",
            {"title": "edited", "content": "c", "excerpt": "e",
             "category": "cat", "status": "draft"},
        )
        self.assertEqual(resp.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, "edited")

    def test_publish_blog_can_publish(self):
        self.client.force_login(staff_with("manage_blog", "publish_blog"))
        resp = self.client.post(
            f"/api/posts/{self.post.pk}/",
            {"title": "t", "content": "c", "excerpt": "e",
             "category": "cat", "status": "published"},
        )
        self.assertEqual(resp.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, "published")

    def test_unpublishing_also_requires_publish_blog(self):
        self.post.status = "published"
        self.post.save(update_fields=["status"])
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            f"/api/posts/{self.post.pk}/",
            {"title": "t", "content": "c", "excerpt": "e",
             "category": "cat", "status": "draft"},
        )
        self.assertEqual(resp.status_code, 403)


class DraftLeakPathsTest(TestCase):
    """Task 6 review finding: drafts leaked through three other paths besides
    the two server-rendered public views (/api/posts/, /api/posts/<pk>/,
    /api/blog-posts/, and the AI chat retriever tool)."""

    def setUp(self):
        self.draft = BlogPost.objects.create(
            title="Secret draft post", content="c", excerpt="e",
            category="cat", status="draft",
        )
        self.live = BlogPost.objects.create(
            title="Live published post", content="c", excerpt="e",
            category="cat", status="published",
        )

    # --- Leak 1: brand/api_views.py post_list / post_detail ---

    def test_anonymous_post_list_hides_draft_title(self):
        resp = self.client.get("/api/posts/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Secret draft post")
        self.assertContains(resp, "Live published post")

    def test_anonymous_post_detail_404s_for_draft(self):
        resp = self.client.get(f"/api/posts/{self.draft.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_staff_without_manage_blog_cannot_see_draft_in_list(self):
        self.client.force_login(staff_with())
        resp = self.client.get("/api/posts/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Secret draft post")

    def test_staff_without_manage_blog_gets_404_for_draft_detail(self):
        self.client.force_login(staff_with())
        resp = self.client.get(f"/api/posts/{self.draft.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_staff_with_manage_blog_sees_draft_in_list(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/api/posts/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Secret draft post")

    def test_staff_with_manage_blog_sees_draft_detail(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get(f"/api/posts/{self.draft.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "draft")

    # --- Leak 2: brand/api.py blog_posts_api ---

    def test_anonymous_blog_posts_api_hides_draft_title(self):
        resp = self.client.get("/api/blog-posts/")
        self.assertEqual(resp.status_code, 200)
        titles = [item["title"] for item in resp.json()]
        self.assertNotIn("Secret draft post", titles)
        self.assertIn("Live published post", titles)

    # --- Leak 3: ai_workflows/tools.py BlogRetrieverTool.search ---

    def test_the_chat_corpus_never_contains_a_draft(self):
        """The retriever used to embed every post and filter drafts at query
        time. Semantic memory has no status column, so that filter moved to
        write time -- which is the stricter half of the trade: a draft is not
        in the corpus at all, rather than one forgotten `.filter()` away from
        being quoted to a visitor.

        Asserted against the store rather than against a search result,
        because "the draft did not come back in the top 5" is also what a
        leaking corpus looks like on a good day.
        """
        from django.contrib.contenttypes.models import ContentType

        from knowledge_base.models import MemoryDocument

        def indexed(post):
            return MemoryDocument.objects.filter(
                content_type=ContentType.objects.get_for_model(BlogPost),
                object_id=post.pk,
            ).exists()

        with patch("ai_workflows.harness.indexing.queue_embedding") as queued:
            self.draft.save()
        self.assertFalse(queued.called, "a draft must not be queued for embedding")
        self.assertFalse(indexed(self.draft))

        with patch("ai_workflows.harness.indexing.queue_embedding") as queued:
            self.live.save()
        self.assertTrue(queued.called, "a published post must be indexed")

    def test_unpublishing_withdraws_a_post_from_the_chat_corpus(self):
        """Taking a post down has to remove it, not merely stop refreshing it.

        `MemoryDocument` addresses its object through a content type and an id
        rather than a foreign key, so nothing cascades and nothing expires.
        Without an explicit withdrawal the assistant would keep answering from
        content that was deliberately retracted.
        """
        from django.contrib.contenttypes.models import ContentType

        from knowledge_base.models import MemoryDocument

        document = MemoryDocument.objects.create(
            content_type=ContentType.objects.get_for_model(BlogPost),
            object_id=self.live.pk, scope="site", kind="blog_post",
            title=self.live.title, text="c",
        )

        self.live.status = "draft"
        self.live.save()

        self.assertFalse(
            MemoryDocument.objects.filter(pk=document.pk).exists(),
            "an unpublished post is still answerable from the chat corpus",
        )

    def test_deleting_a_post_withdraws_it_from_the_chat_corpus(self):
        from django.contrib.contenttypes.models import ContentType

        from knowledge_base.models import MemoryDocument

        document = MemoryDocument.objects.create(
            content_type=ContentType.objects.get_for_model(BlogPost),
            object_id=self.live.pk, scope="site", kind="blog_post",
            title=self.live.title, text="c",
        )

        self.live.delete()

        self.assertFalse(MemoryDocument.objects.filter(pk=document.pk).exists())


class PanelFormStatusTest(TestCase):
    """The panel's status control, from the server's side.

    The select is rendered disabled for a user without publish_blog, and a
    disabled control is omitted from FormData - so these requests carry no
    status key at all. That must remain a normal, successful edit.
    """

    def setUp(self):
        self.draft = BlogPost.objects.create(
            title="t", content="c", excerpt="e", category="cat", status="draft"
        )
        self.live = BlogPost.objects.create(
            title="t2", content="c", excerpt="e", category="cat", status="published"
        )

    def test_edit_without_a_status_key_succeeds_and_keeps_the_status(self):
        self.client.force_login(staff_with("manage_blog"))
        for post in (self.draft, self.live):
            before = post.status
            resp = self.client.post(
                f"/api/posts/{post.pk}/",
                {"title": "edited", "content": "c", "excerpt": "e",
                 "category": "cat"},
            )
            self.assertEqual(resp.status_code, 200)
            post.refresh_from_db()
            self.assertEqual(post.title, "edited")
            self.assertEqual(post.status, before)

    def test_resubmitting_the_current_status_is_not_a_publish(self):
        """Posting the status a post already has is not a transition.

        The actor here holds only manage_blog, so this also covers the case
        where someone re-enables the disabled control in devtools and submits
        the unchanged value: no transition, so no publish_blog needed.
        """
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            f"/api/posts/{self.live.pk}/",
            {"title": "edited", "content": "c", "excerpt": "e",
             "category": "cat", "status": "published"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_an_unknown_status_is_rejected(self):
        self.client.force_login(staff_with("manage_blog", "publish_blog"))
        resp = self.client.post(
            f"/api/posts/{self.draft.pk}/",
            {"title": "t", "content": "c", "excerpt": "e",
             "category": "cat", "status": "bogus"},
        )
        self.assertEqual(resp.status_code, 400)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, "draft")


class CreateWithStatusTest(TestCase):
    """Creating straight into published is a publish and is gated as one."""

    payload = {"title": "n", "content": "c", "excerpt": "e", "category": "cat"}

    def test_create_defaults_to_draft(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post("/api/posts/", self.payload)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(BlogPost.objects.get(title="n").status, "draft")

    def test_create_as_published_needs_publish_blog(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            "/api/posts/", {**self.payload, "status": "published"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(BlogPost.objects.filter(title="n").exists())

    def test_create_as_published_with_publish_blog(self):
        self.client.force_login(staff_with("manage_blog", "publish_blog"))
        resp = self.client.post(
            "/api/posts/", {**self.payload, "status": "published"}
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(BlogPost.objects.get(title="n").status, "published")

    def test_create_with_an_unknown_status_is_rejected(self):
        self.client.force_login(staff_with("manage_blog", "publish_blog"))
        resp = self.client.post("/api/posts/", {**self.payload, "status": "bogus"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(BlogPost.objects.filter(title="n").exists())
