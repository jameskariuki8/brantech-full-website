from django.test import TestCase

from messaging import rendering


class RenderingTests(TestCase):
    CONTEXT = {
        "name": "Ben & Jerry",
        "first_name": "Ben",
        "email": "ben@example.com",
        "unsubscribe_url": "http://u/1",
    }

    def test_render_text_substitutes_without_escaping(self):
        out = rendering.render_text("Hi {{ name }}", self.CONTEXT)
        self.assertEqual(out, "Hi Ben & Jerry")

    def test_render_html_escapes_values(self):
        out = rendering.render_html("<p>Hi {{ name }}</p>", self.CONTEXT)
        self.assertIn("Ben &amp; Jerry", out)
        self.assertNotIn("Ben & Jerry", out)

    def test_render_html_escapes_angle_brackets_in_values(self):
        out = rendering.render_html("<p>{{ name }}</p>", {"name": "<script>x</script>"})
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_unknown_placeholder_renders_empty(self):
        out = rendering.render_html("<p>Hi {{ compnay }}!</p>", self.CONTEXT)
        self.assertEqual(out, "<p>Hi !</p>")

    def test_whitespace_variants_resolve(self):
        out = rendering.render_text("{{name}}|{{ name }}|{{  name  }}", self.CONTEXT)
        self.assertEqual(out, "Ben & Jerry|Ben & Jerry|Ben & Jerry")

    def test_subject_and_body_accept_the_same_keys(self):
        subject = rendering.render_text("{{ first_name }} - {{ year }}", {"first_name": "Ben", "year": "2026"})
        body = rendering.render_html("{{ first_name }} - {{ year }}", {"first_name": "Ben", "year": "2026"})
        self.assertEqual(subject, "Ben - 2026")
        self.assertEqual(body, "Ben - 2026")

    def test_html_to_text_strips_tags_and_unescapes_entities(self):
        self.assertEqual(
            rendering.html_to_text("<p>Hello <b>world</b> &amp; friends</p>").strip(),
            "Hello world & friends",
        )
