from django.test import TestCase

from messaging import emailhtml


class SanitizeTests(TestCase):
    def test_strips_script_tag(self):
        out = emailhtml.sanitize_email_html("<p>hi</p><script>alert(1)</script>")
        self.assertNotIn("script", out)
        self.assertIn("<p>hi</p>", out)

    def test_strips_event_handlers_but_keeps_link(self):
        out = emailhtml.sanitize_email_html('<a href="http://x.com" onclick="bad()">l</a>')
        self.assertNotIn("onclick", out)
        self.assertIn('href="http://x.com"', out)

    def test_keeps_style_attribute_and_image(self):
        out = emailhtml.sanitize_email_html(
            '<p style="color:red">hi</p><img src="i.png" alt="a">'
        )
        self.assertIn('style="color:red"', out)
        self.assertIn('src="i.png"', out)

    def test_empty_input_is_safe(self):
        self.assertEqual(emailhtml.sanitize_email_html(""), "")
        self.assertEqual(emailhtml.sanitize_email_html(None), "")


class InlineTests(TestCase):
    def test_base_css_becomes_inline_style(self):
        out = emailhtml.inline_email_css("<p>hi</p>")
        self.assertIn("<p", out)
        self.assertIn("style=", out)

    def test_link_gets_inlined_colour(self):
        out = emailhtml.inline_email_css('<a href="http://x.com">l</a>')
        self.assertIn("style=", out)

    def test_empty_input_is_safe(self):
        self.assertEqual(emailhtml.inline_email_css(""), "")
        self.assertEqual(emailhtml.inline_email_css(None), "")
