from unittest.mock import MagicMock, patch

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

    def test_blog_retriever_tool_excludes_drafts(self):
        self.draft.embedding = [0.1] * 3072
        self.draft.save(update_fields=["embedding"])
        self.live.embedding = [0.1] * 3072
        self.live.save(update_fields=["embedding"])

        # Patch the embeddings seam (ai_workflows.tools.get_embeddings) so
        # BlogRetrieverTool.__init__ never touches the real Gemini API.
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1] * 3072
        with patch("ai_workflows.tools.get_embeddings", return_value=mock_embeddings):
            from ai_workflows.tools import BlogRetrieverTool
            tool = BlogRetrieverTool()
            result = tool.search("anything", k=5)

        self.assertIn("Live published post", result)
        self.assertNotIn("Secret draft post", result)


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
