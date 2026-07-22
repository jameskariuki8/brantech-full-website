"""Access control on the public content APIs.

These endpoints are readable by anyone (the public blog and projects pages
fetch them), but writing must require staff plus the relevant capability
(manage_blog / manage_projects). The duplicate router viewsets in api.py and
the unused /api/events/ route have been deleted; DeletedRouteTest confirms
they stay gone.
"""

from django.contrib.auth.models import Permission, User
from django.test import TestCase

from brand.models import BlogPost, Project


class ContentApiReadAccessTest(TestCase):
    """Reads stay public -- the marketing site depends on them."""

    def setUp(self):
        BlogPost.objects.create(title="t", content="c", excerpt="e", category="cat")
        Project.objects.create(
            title="t", description="d", short_description="s"
        )

    def test_anonymous_can_list_posts(self):
        self.assertEqual(self.client.get("/api/posts/").status_code, 200)

    def test_anonymous_can_list_projects(self):
        self.assertEqual(self.client.get("/api/projects/").status_code, 200)


class ContentApiWriteRequiresStaffTest(TestCase):
    """A signed-up but non-staff user must not be able to write."""

    def setUp(self):
        self.user = User.objects.create_user("randomer", password="p")
        self.post = BlogPost.objects.create(
            title="victim", content="c", excerpt="e", category="cat"
        )
        self.project = Project.objects.create(
            title="victim", description="d", short_description="s"
        )

    def test_non_staff_cannot_create_post(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/posts/",
            {"title": "pwned", "content": "x", "excerpt": "x", "category": "x"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(BlogPost.objects.filter(title="pwned").exists())

    def test_non_staff_cannot_delete_post(self):
        self.client.force_login(self.user)
        resp = self.client.delete(f"/api/posts/{self.post.pk}/")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(BlogPost.objects.filter(pk=self.post.pk).exists())

    def test_non_staff_cannot_create_project(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/projects/",
            {"title": "pwned", "description": "x", "short_description": "x"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Project.objects.filter(title="pwned").exists())

    def test_non_staff_cannot_delete_project(self):
        self.client.force_login(self.user)
        resp = self.client.delete(f"/api/projects/{self.project.pk}/")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

    def test_anonymous_cannot_create_post(self):
        resp = self.client.post(
            "/api/posts/",
            {"title": "pwned", "content": "x", "excerpt": "x", "category": "x"},
        )
        self.assertIn(resp.status_code, (401, 403))
        self.assertFalse(BlogPost.objects.filter(title="pwned").exists())


class StaffCanStillWriteTest(TestCase):
    """The fix must not lock the admin panel out of its own endpoints."""

    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.staff.user_permissions.add(
            *Permission.objects.filter(
                codename__in=("manage_blog", "manage_projects"),
                content_type__app_label="staff",
            )
        )
        self.staff = User.objects.get(pk=self.staff.pk)
        self.client.force_login(self.staff)

    def test_staff_can_create_post(self):
        resp = self.client.post(
            "/api/posts/",
            {"title": "legit", "content": "x", "excerpt": "x", "category": "x"},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(BlogPost.objects.filter(title="legit").exists())

    def test_staff_can_delete_post(self):
        post = BlogPost.objects.create(
            title="doomed", content="c", excerpt="e", category="cat"
        )
        resp = self.client.delete(f"/api/posts/{post.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(BlogPost.objects.filter(pk=post.pk).exists())

    def test_staff_can_create_project(self):
        resp = self.client.post(
            "/api/projects/",
            {"title": "legit", "description": "x", "short_description": "x"},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Project.objects.filter(title="legit").exists())


def staff_with(*codenames):
    user = User.objects.create_user("cap", password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class ContentCapabilityTest(TestCase):
    def setUp(self):
        self.post = BlogPost.objects.create(
            title="t", content="c", excerpt="e", category="cat"
        )

    def test_staff_without_manage_blog_cannot_create(self):
        self.client.force_login(staff_with())
        resp = self.client.post(
            "/api/posts/",
            {"title": "x", "content": "c", "excerpt": "e", "category": "cat"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_manage_blog_can_create(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            "/api/posts/",
            {"title": "x", "content": "c", "excerpt": "e", "category": "cat"},
        )
        self.assertEqual(resp.status_code, 201)

    def test_manage_blog_does_not_grant_project_access(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            "/api/projects/",
            {"title": "x", "description": "d", "short_description": "s"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_manage_projects_can_create_projects(self):
        self.client.force_login(staff_with("manage_projects"))
        resp = self.client.post(
            "/api/projects/",
            {"title": "x", "description": "d", "short_description": "s"},
        )
        self.assertEqual(resp.status_code, 201)

    def test_reads_remain_public(self):
        self.assertEqual(self.client.get("/api/posts/").status_code, 200)
        self.assertEqual(self.client.get("/api/projects/").status_code, 200)


class DeletedRouteTest(TestCase):
    """The duplicate router routes and the unused events route are gone."""

    def test_events_route_is_gone(self):
        self.assertEqual(self.client.get("/api/events/").status_code, 404)

    def test_posts_format_suffix_route_is_gone(self):
        self.assertEqual(self.client.get("/api/posts.json").status_code, 404)

    def test_projects_format_suffix_route_is_gone(self):
        self.assertEqual(self.client.get("/api/projects.json").status_code, 404)
