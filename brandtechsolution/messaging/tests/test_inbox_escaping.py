from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.test import SimpleTestCase


class InboxEscapingTests(SimpleTestCase):
    """
    Lightweight regression guard for the stored-XSS fix in the admin panel's
    Inbox section. This does NOT execute the JS or verify runtime DOM output
    (Django's test framework has no JS engine) - it only inspects the shipped
    source text to ensure the unsafe raw interpolations were replaced with
    escapeHtml(...) calls, and that the helper itself exists. It cannot catch
    a regression where escapeHtml is defined but silently broken, or where
    escaping is bypassed at runtime some other way.
    """

    def _read_static(self, rel_path):
        found = find(rel_path)
        self.assertIsNotNone(found, f"Could not locate static file: {rel_path}")
        with open(found, "r", encoding="utf-8") as f:
            return f.read()

    def test_inbox_js_escapes_untrusted_mail_fields(self):
        js = self._read_static("brand/js/admin/inbox.js")
        for escaped in [
            "escapeHtml(who)",
            "escapeHtml(t.subject",
            "escapeHtml(t.snippet)",
            "escapeHtml(m.from_email)",
            "escapeHtml(main)",
            "escapeHtml(quoted)",
            "escapeHtml(a.name)",
        ]:
            self.assertIn(
                escaped, js,
                f"Expected {escaped!r} in inbox.js to escape untrusted mail data."
            )
        for raw in ["${t.subject}", "${t.snippet}", "${m.from_email}", "${m.body_text}", "${who}"]:
            self.assertNotIn(raw, js, f"Unescaped interpolation {raw!r} in inbox.js.")

    def test_html_bodies_render_only_in_a_scriptless_sandbox(self):
        js = self._read_static("brand/js/admin/inbox.js")
        self.assertIn('sandbox="allow-same-origin allow-popups', js)
        self.assertNotIn("allow-scripts", js)
        self.assertIn("default-src \\'none\\'", js)

    def test_core_js_defines_escape_html_helper(self):
        js = self._read_static("brand/js/admin/core.js")
        self.assertIn("function escapeHtml", js)
