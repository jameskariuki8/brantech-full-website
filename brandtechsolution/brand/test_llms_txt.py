from django.test import TestCase

from brand.models import BlogPost


class LlmsTxtTest(TestCase):
    def setUp(self):
        self.published = BlogPost.objects.create(
            title="Scaling pgvector", slug="scaling-pgvector",
            excerpt="What broke at ten million embeddings.",
            content="body", status="published",
        )
        self.draft = BlogPost.objects.create(
            title="Unfinished thoughts", slug="unfinished-thoughts",
            excerpt="Not ready.", content="body", status="draft",
        )

    def test_it_is_served_at_the_conventional_path(self):
        """llmstxt.org specifies /llms.txt exactly - no trailing slash."""
        response = self.client.get("/llms.txt")

        self.assertEqual(response.status_code, 200)

    def test_it_is_plain_text_so_a_browser_shows_it(self):
        response = self.client.get("/llms.txt")

        self.assertTrue(
            response["Content-Type"].startswith("text/plain"),
            response["Content-Type"],
        )

    def test_it_opens_with_a_title_and_a_blockquote_summary(self):
        """The format is an H1 then a > summary; parsers rely on both."""
        body = self.client.get("/llms.txt").content.decode()

        lines = [ln for ln in body.splitlines() if ln.strip()]
        self.assertTrue(lines[0].startswith("# "), lines[0])
        self.assertTrue(lines[1].startswith("> "), lines[1])

    def test_it_lists_published_posts(self):
        body = self.client.get("/llms.txt").content.decode()

        self.assertIn("Scaling pgvector", body)
        self.assertIn("/blog/scaling-pgvector/", body)

    def test_it_does_not_leak_drafts(self):
        """The same rule the public blog follows - a draft 404s for the
        public, so naming one here would be a disclosure by another door."""
        body = self.client.get("/llms.txt").content.decode()

        self.assertNotIn("Unfinished thoughts", body)
        self.assertNotIn("unfinished-thoughts", body)

    def test_links_are_absolute(self):
        """Relative links are useless to a model that fetched this file
        without remembering which host it came from."""
        body = self.client.get("/llms.txt").content.decode()

        self.assertIn("https://", body)
        self.assertNotIn("](/", body)

    def test_it_is_reachable_without_signing_in(self):
        response = self.client.get("/llms.txt")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("login", response["Content-Type"])
