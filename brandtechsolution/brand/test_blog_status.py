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
