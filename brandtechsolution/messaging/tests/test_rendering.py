from django.test import TestCase
from messaging import rendering


class RenderingTests(TestCase):
    def test_render_body_substitutes_placeholders(self):
        out = rendering.render_body(
            "<p>Hi {{ name }}</p><a href='{{ unsubscribe_url }}'>x</a>",
            name="Ada", unsubscribe_url="http://u/1",
        )
        self.assertIn("Hi Ada", out)
        self.assertIn("http://u/1", out)
        self.assertNotIn("{{", out)

    def test_render_body_blank_name(self):
        out = rendering.render_body("<p>Hi {{ name }}</p>", name="", unsubscribe_url="u")
        self.assertIn("<p>Hi </p>", out)

    def test_html_to_text_strips_tags(self):
        self.assertEqual(rendering.html_to_text("<p>Hello <b>world</b></p>").strip(), "Hello world")
