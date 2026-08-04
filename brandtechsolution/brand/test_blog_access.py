"""Public blog endpoints must not expose drafts or moderated comments.

Four endpoints take an integer primary key straight from the URL. blog_detail
has always filtered on status='published'; the other three did not, so a
visitor could walk the id space and read drafts in full -- including the
editorial pipeline's standing queue of generated articles awaiting approval.
"""
import json

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from brand.models import BlogComment, BlogLike, BlogPost


class BlogAccessTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.published = BlogPost.objects.create(
            title="Published Post",
            excerpt="visible",
            content="public body",
            status="published",
        )
        self.draft = BlogPost.objects.create(
            title="Unreleased Draft",
            excerpt="secret",
            content="embargoed body",
            status="draft",
        )


class DraftExposureTest(BlogAccessTestCase):
    def test_blog_json_refuses_a_draft(self):
        res = self.client.get(reverse('blog_json', args=[self.draft.pk]))
        self.assertEqual(res.status_code, 404)

    def test_blog_json_still_serves_a_published_post(self):
        res = self.client.get(reverse('blog_json', args=[self.published.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['title'], "Published Post")

    def test_draft_body_never_appears_in_any_response(self):
        """The point of the fix: the draft's text must not be reachable."""
        for name in ('blog_json', 'get_blog_comments'):
            res = self.client.get(reverse(name, args=[self.draft.pk]))
            self.assertNotContains(res, "embargoed body", status_code=404)

    def test_comments_endpoint_refuses_a_draft(self):
        res = self.client.get(reverse('get_blog_comments', args=[self.draft.pk]))
        self.assertEqual(res.status_code, 404)

    def test_like_refuses_a_draft(self):
        res = self.client.post(
            reverse('like_blog_post', args=[self.draft.pk]),
            data=json.dumps({'browser_id': 'abc'}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(BlogLike.objects.count(), 0)

    @override_settings(TURNSTILE_SECRET_KEY="")
    def test_comment_refuses_a_draft(self):
        res = self.client.post(
            reverse('comment_blog_post', args=[self.draft.pk]),
            data=json.dumps({'browser_id': 'abc', 'content': 'hello'}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(BlogComment.objects.count(), 0)


class ModeratedCommentTest(BlogAccessTestCase):
    def test_unapproved_comments_are_not_served(self):
        """A comment a moderator took down must vanish from the API too.

        is_approved defaults to True, so this is not about a review queue --
        it is about a takedown that only removed the comment from the page.
        """
        BlogComment.objects.create(
            post=self.published, browser_id='b1', content='fine', is_approved=True
        )
        BlogComment.objects.create(
            post=self.published, browser_id='b2', content='abusive', is_approved=False
        )

        res = self.client.get(reverse('get_blog_comments', args=[self.published.pk]))
        self.assertEqual(res.status_code, 200)
        bodies = [c['content'] for c in res.json()['comments']]
        self.assertIn('fine', bodies)
        self.assertNotIn('abusive', bodies)


@override_settings(BLOG_LIKE_RATE_LIMIT_COUNT=3, BLOG_LIKE_RATE_LIMIT_WINDOW_SECONDS=60)
class LikeThrottleTest(BlogAccessTestCase):
    def _like(self, browser_id):
        return self.client.post(
            reverse('like_blog_post', args=[self.published.pk]),
            data=json.dumps({'browser_id': browser_id}),
            content_type='application/json',
        )

    def test_a_rotating_browser_id_is_still_throttled(self):
        """browser_id is client-supplied, so the throttle must key on address.

        Keying on browser_id would be defeated by the one line of script this
        is meant to stop.
        """
        for i in range(3):
            self.assertEqual(self._like(f'id-{i}').status_code, 200)

        blocked = self._like('id-4')
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(BlogLike.objects.count(), 3)

    def test_a_different_address_has_its_own_allowance(self):
        for i in range(3):
            self._like(f'id-{i}')

        res = self.client.post(
            reverse('like_blog_post', args=[self.published.pk]),
            data=json.dumps({'browser_id': 'other'}),
            content_type='application/json',
            HTTP_CF_CONNECTING_IP='203.0.113.9',
        )
        self.assertEqual(res.status_code, 200)

    def test_a_like_below_the_limit_still_toggles_off(self):
        self.assertTrue(self._like('same').json()['liked'])
        self.assertFalse(self._like('same').json()['liked'])
        self.assertEqual(BlogLike.objects.count(), 0)
