"""Access control on the newsroom endpoints.

These views shipped unauthenticated and CSRF-exempt. /editorial/api/
articles/<id>/approve/ publishes to the live public site and
/editorial/api/run-pipeline/ spends model quota, both reachable by anyone who
knew the URL. This module pins the gates so they cannot quietly come off
again.
"""
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from editorial.models import EditorialArticle

PUBLISHING = [
    "/editorial/api/run-pipeline/",
    "/editorial/api/articles/{id}/approve/",
    "/editorial/api/articles/{id}/reject/",
]

READING = [
    "/editorial/dashboard/",
    "/editorial/api/articles/{id}/",
    "/editorial/api/articles/{id}/export-docx/",
    "/editorial/api/knowledge-search/?q=test",
]


def staff_with(*codenames):
    user = User.objects.create_user("u", password="pw", is_staff=True)
    if codenames:
        group = Group.objects.create(name="role")
        group.permissions.set([
            Permission.objects.get(codename=c, content_type__app_label="staff")
            for c in codenames
        ])
        user.groups.add(group)
    return user


class AnonymousAccessTest(TestCase):
    def setUp(self):
        self.article = EditorialArticle.objects.create(title="Draft", slug="draft")

    def test_anonymous_cannot_reach_publishing_endpoints(self):
        for path in PUBLISHING:
            with self.subTest(path=path):
                response = self.client.post(path.format(id=self.article.pk))
                # capability_required bounces anonymous users to the login
                # page rather than 403ing them.
                self.assertIn(response.status_code, (302, 403))

    def test_anonymous_cannot_reach_reading_endpoints(self):
        for path in READING:
            with self.subTest(path=path):
                response = self.client.get(path.format(id=self.article.pk))
                self.assertIn(response.status_code, (302, 403))

    def test_anonymous_cannot_publish_to_the_live_site(self):
        """The finding that mattered most: this created a public BlogPost."""
        from brand.models import BlogPost

        before = BlogPost.objects.count()
        self.client.post(f"/editorial/api/articles/{self.article.pk}/approve/")

        self.assertEqual(BlogPost.objects.count(), before)
        self.article.refresh_from_db()
        self.assertNotEqual(self.article.status, "published")


class CapabilityBoundaryTest(TestCase):
    def setUp(self):
        self.article = EditorialArticle.objects.create(title="Draft", slug="draft")

    def test_staff_without_capabilities_is_refused(self):
        self.client.force_login(staff_with())
        for path in PUBLISHING + READING:
            with self.subTest(path=path):
                response = self.client.get(path.format(id=self.article.pk))
                self.assertEqual(response.status_code, 403)

    def test_manage_blog_alone_cannot_publish(self):
        """Approving here IS publishing, so it must need publish_blog - the
        same capability that gates draft -> published for ordinary posts."""
        self.client.force_login(staff_with("manage_blog"))

        response = self.client.post(
            f"/editorial/api/articles/{self.article.pk}/approve/"
        )

        self.assertEqual(response.status_code, 403)

    def test_manage_blog_can_read_the_newsroom(self):
        self.client.force_login(staff_with("manage_blog"))

        self.assertEqual(self.client.get("/editorial/dashboard/").status_code, 200)

    def test_pipeline_trigger_needs_publish_blog(self):
        """It can auto_publish, so it is a publishing action."""
        self.client.force_login(staff_with("manage_blog"))

        response = self.client.post("/editorial/api/run-pipeline/")

        self.assertEqual(response.status_code, 403)


class CsrfTest(TestCase):
    """@csrf_exempt was removed; the protection has to actually apply now."""

    def setUp(self):
        self.article = EditorialArticle.objects.create(title="Draft", slug="draft")

    def test_publishing_post_without_a_csrf_token_is_rejected(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(staff_with("manage_blog", "publish_blog"))

        response = client.post(
            f"/editorial/api/articles/{self.article.pk}/approve/"
        )

        self.assertEqual(response.status_code, 403)
