"""Access control on the public content APIs.

These endpoints are readable by anyone (the public blog and projects pages
fetch them), but writing must require a staff account. Two separate route
sets reach the same models -- the function views in api_views.py and the
router viewsets in api.py -- so both are covered here.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from brand.models import BlogPost, Event, Project


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


class EventApiPermissionTest(TestCase):
    """/api/events/ is a router viewset with no shadowing function view."""

    EVENT = {
        "title": "anon event",
        "description": "x",
        "event_type": "webinar",
        "date": "2027-01-01T10:00:00Z",
    }

    def test_anonymous_cannot_create_event(self):
        resp = self.client.post("/api/events/", self.EVENT)
        self.assertIn(resp.status_code, (401, 403))
        self.assertFalse(Event.objects.filter(title="anon event").exists())

    def test_anonymous_cannot_delete_event(self):
        ev = Event.objects.create(
            title="victim", description="x", event_type="webinar",
            date="2027-01-01T10:00:00Z",
        )
        resp = self.client.delete(f"/api/events/{ev.pk}/")
        self.assertIn(resp.status_code, (401, 403))
        self.assertTrue(Event.objects.filter(pk=ev.pk).exists())

    def test_non_staff_cannot_create_event(self):
        self.client.force_login(User.objects.create_user("randomer", password="p"))
        resp = self.client.post("/api/events/", self.EVENT)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Event.objects.filter(title="anon event").exists())

    def test_staff_can_create_event(self):
        self.client.force_login(
            User.objects.create_user("staff", password="p", is_staff=True)
        )
        resp = self.client.post("/api/events/", self.EVENT)
        self.assertEqual(resp.status_code, 201)


class RouterBypassTest(TestCase):
    """The function views shadow the router only on <int:pk> paths.

    DRF's DefaultRouter also serves format-suffixed routes such as
    /api/posts.json, which no function view shadows. If the viewsets are
    unprotected, those are an unauthenticated way to the same models.
    """

    def test_anonymous_cannot_create_post_via_format_suffix(self):
        resp = self.client.post(
            "/api/posts.json",
            {"title": "pwned", "content": "x", "excerpt": "x", "category": "x"},
        )
        self.assertIn(resp.status_code, (401, 403))
        self.assertFalse(BlogPost.objects.filter(title="pwned").exists())

    def test_anonymous_cannot_create_project_via_format_suffix(self):
        resp = self.client.post(
            "/api/projects.json",
            {"title": "pwned", "description": "x", "short_description": "x"},
        )
        self.assertIn(resp.status_code, (401, 403))
        self.assertFalse(Project.objects.filter(title="pwned").exists())
