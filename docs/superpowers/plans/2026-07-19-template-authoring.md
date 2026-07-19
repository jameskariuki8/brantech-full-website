# Template Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw-HTML textarea and hardcoded placeholder substitution with a placeholder registry, a restricted WYSIWYG editor whose output is sanitized and CSS-inlined for email clients, and a true-fidelity server-rendered preview.

**Architecture:** A single placeholder registry (`placeholders.py`) is the source of truth for the renderer, the insert-menu UI, and preview sample data. `rendering.py` becomes context-driven with HTML escaping. `emailhtml.py` sanitizes with `nh3` then inlines CSS with `css-inline`. Both `EmailTemplate` and `Campaign` store `body_source` (editable, sanitized, not inlined) and `body_html` (derived, inlined, used for sending), so editing is lossless.

**Tech Stack:** Django, Django REST Framework, `nh3` (already a dependency), `css-inline` (new), Quill 2.x via CDN. Tests use Django `TestCase` run with `manage.py test`.

## Global Constraints

- **Working directory:** `/home/bigaddict/Projects/Codebases/brantech-full-website/brandtechsolution` (contains `manage.py`). Python is `./.venv/bin/python`.
- **Test runner:** Django `TestCase`. Run `./.venv/bin/python manage.py test messaging --keepdb -v 2` (NOT pytest). `--keepdb` avoids slow Postgres test-DB recreation.
- **Branch:** work on `master` unless told otherwise; commit trailer required: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **All admin endpoints MUST set `permission_classes = [IsAdminUser]`** — DRF defaults to `AllowAny` in this project. Do NOT use `csrf_exempt` on new endpoints.
- **Do NOT write to the real dev database.** Use the Django test framework (it builds a throwaway test DB). Never run ad-hoc scripts against the dev DB.
- **Do NOT send real email.** Tests use the locmem backend.
- **Never regress the stored-XSS fix:** untrusted values interpolated into admin-panel `innerHTML` must go through the existing `escapeHtml()` helper in `core.js`.
- **Placeholder syntax:** `{{ key }}`, whitespace-tolerant. Unknown keys render as the empty string; the editor warns before save.
- **`body_html` is read-only via the API.** Clients submit `body_source`; the server derives `body_html = inline_email_css(body_source)`.
- **Existing suite is 67 tests and must stay green.**

## File Structure

| File | Responsibility |
|---|---|
| `messaging/placeholders.py` (new) | Registry, context building, placeholder discovery |
| `messaging/rendering.py` (rewrite) | Substitute placeholders into text/HTML; HTML→text |
| `messaging/emailhtml.py` (new) | Sanitize + CSS-inline stored body HTML |
| `messaging/models.py` (modify) | `body_source` on `EmailTemplate` and `Campaign` |
| `messaging/serializers.py` (modify) | `EmailBodyMixin` deriving `body_html` from `body_source` |
| `messaging/api.py` (modify) | `placeholders` + `preview` endpoints |
| `messaging/api_urls.py` (modify) | Routes for the two endpoints |
| `messaging/management/commands/process_email_outbox.py` (modify) | Use the new renderer API |
| `brand/static/brand/js/admin/editor.js` (new) | Quill factory, placeholder insert, source toggle, preview |
| `brand/templates/brand/admin/_templates.html` (modify) | Editor + preview controls |
| `brand/templates/brand/admin/_campaigns.html` (modify) | Editor + preview controls |

---

### Task 1: Placeholder registry

**Files:**
- Create: `brandtechsolution/messaging/placeholders.py`
- Create: `brandtechsolution/messaging/tests/test_placeholders.py`

**Interfaces:**
- Produces:
  - `PLACEHOLDERS: list[dict]` — each `{"key", "label", "description", "sample"}`
  - `PLACEHOLDER_KEYS: set[str]`
  - `PLACEHOLDER_RE: re.Pattern` — matches `{{ key }}`, capturing the key
  - `build_context(recipient, unsubscribe_url, now=None, extra=None) -> dict[str, str]`
  - `sample_context() -> dict[str, str]`
  - `find_placeholders(text) -> list[str]`
  - `unknown_placeholders(text) -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `brandtechsolution/messaging/tests/test_placeholders.py`:
```python
from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from messaging import placeholders
from messaging.models import Campaign, CampaignRecipient


class PlaceholderTests(TestCase):
    def setUp(self):
        self.campaign = Campaign.objects.create(
            name="C", subject="s", body_html="<p>x</p>"
        )
        self.recipient = CampaignRecipient.objects.create(
            campaign=self.campaign, email="ada@example.com", name="Ada Lovelace"
        )

    def test_build_context_core_keys(self):
        now = timezone.make_aware(datetime(2026, 7, 19, 12, 0))
        ctx = placeholders.build_context(self.recipient, "http://u/1", now=now)
        self.assertEqual(ctx["name"], "Ada Lovelace")
        self.assertEqual(ctx["first_name"], "Ada")
        self.assertEqual(ctx["email"], "ada@example.com")
        self.assertEqual(ctx["date"], "July 19, 2026")
        self.assertEqual(ctx["year"], "2026")
        self.assertEqual(ctx["unsubscribe_url"], "http://u/1")

    def test_first_name_blank_when_name_blank(self):
        r = CampaignRecipient.objects.create(
            campaign=self.campaign, email="x@example.com", name=""
        )
        ctx = placeholders.build_context(r, "http://u/2")
        self.assertEqual(ctx["first_name"], "")
        self.assertEqual(ctx["name"], "")

    def test_extra_overrides_and_stringifies(self):
        ctx = placeholders.build_context(
            self.recipient, "http://u/1", extra={"company": "Analytical Ltd", "n": 5}
        )
        self.assertEqual(ctx["company"], "Analytical Ltd")
        self.assertEqual(ctx["n"], "5")

    def test_find_placeholders_tolerates_whitespace(self):
        found = placeholders.find_placeholders("{{name}} {{ email }} {{  year  }}")
        self.assertEqual(found, ["name", "email", "year"])

    def test_unknown_placeholders_reports_only_unknown_once(self):
        text = "{{ name }} {{ compnay }} {{ compnay }} {{ email }}"
        self.assertEqual(placeholders.unknown_placeholders(text), ["compnay"])

    def test_sample_context_covers_every_registered_key(self):
        samples = placeholders.sample_context()
        self.assertEqual(set(samples), placeholders.PLACEHOLDER_KEYS)
        self.assertTrue(all(v for v in samples.values()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python manage.py test messaging.tests.test_placeholders --keepdb -v 2`
Expected: FAIL — `ImportError: cannot import name 'placeholders'` (module does not exist).

- [ ] **Step 3: Write the implementation**

Create `brandtechsolution/messaging/placeholders.py`:
```python
"""Single source of truth for email merge placeholders.

The renderer, the admin-panel insert menu, and the preview endpoint all read
from this registry so they cannot drift apart.
"""
import re

from django.utils import timezone

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

PLACEHOLDERS = [
    {
        "key": "name",
        "label": "Full name",
        "description": "Recipient's full name. May be blank for imported addresses.",
        "sample": "Ada Lovelace",
    },
    {
        "key": "first_name",
        "label": "First name",
        "description": "First word of the recipient's name.",
        "sample": "Ada",
    },
    {
        "key": "email",
        "label": "Email address",
        "description": "Recipient's email address.",
        "sample": "ada@example.com",
    },
    {
        "key": "date",
        "label": "Send date",
        "description": "Date the email is sent, e.g. July 19, 2026.",
        "sample": "July 19, 2026",
    },
    {
        "key": "year",
        "label": "Year",
        "description": "Year the email is sent.",
        "sample": "2026",
    },
    {
        "key": "unsubscribe_url",
        "label": "Unsubscribe link",
        "description": "Per-recipient unsubscribe URL. Added automatically if you omit it.",
        "sample": "https://example.com/unsubscribe/sample-token/",
    },
]

PLACEHOLDER_KEYS = {entry["key"] for entry in PLACEHOLDERS}


def build_context(recipient, unsubscribe_url, now=None, extra=None):
    """Resolve placeholder values for one recipient.

    `now` is injectable so date-dependent tests are deterministic.
    `extra` lets future per-recipient fields join without a renderer change.
    """
    now = now or timezone.localtime()
    name = (recipient.name or "").strip()
    context = {
        "name": name,
        "first_name": name.split()[0] if name else "",
        "email": recipient.email or "",
        "date": now.strftime("%B %d, %Y"),
        "year": str(now.year),
        "unsubscribe_url": unsubscribe_url or "",
    }
    if extra:
        context.update(
            {key: ("" if value is None else str(value)) for key, value in extra.items()}
        )
    return context


def sample_context():
    """Placeholder values used to render the editor preview."""
    return {entry["key"]: entry["sample"] for entry in PLACEHOLDERS}


def find_placeholders(text):
    """Every placeholder key appearing in `text`, in order, including duplicates."""
    return PLACEHOLDER_RE.findall(text or "")


def unknown_placeholders(text):
    """Placeholder keys in `text` that the registry does not define, de-duplicated."""
    unknown = []
    for key in find_placeholders(text):
        if key not in PLACEHOLDER_KEYS and key not in unknown:
            unknown.append(key)
    return unknown
```

Note: `"%B %d, %Y"` renders a zero-padded day (`July 19, 2026`); the test asserts exactly that.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python manage.py test messaging.tests.test_placeholders --keepdb -v 2`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add brandtechsolution/messaging/placeholders.py brandtechsolution/messaging/tests/test_placeholders.py
git commit -m "feat(messaging): placeholder registry with core merge fields

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Context-driven renderer + send-command update

**Files:**
- Rewrite: `brandtechsolution/messaging/rendering.py`
- Modify: `brandtechsolution/messaging/management/commands/process_email_outbox.py:13` (imports) and `:142-151` (`_send_one` head)
- Modify: `brandtechsolution/messaging/tests/test_rendering.py` (existing file — replace its tests)

**Interfaces:**
- Consumes: `messaging.placeholders.PLACEHOLDER_RE`, `build_context` (Task 1)
- Produces:
  - `render_text(template_str, context) -> str` — no escaping (subject, plain-text part)
  - `render_html(template_str, context) -> str` — values HTML-escaped (HTML body)
  - `html_to_text(html) -> str` — strips tags AND unescapes entities

**Removed:** `render_subject(subject, name)` and `render_body(body_html, name, unsubscribe_url)`. Every call site is updated in this task.

- [ ] **Step 1: Replace the rendering tests**

Replace the entire contents of `brandtechsolution/messaging/tests/test_rendering.py` with:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python manage.py test messaging.tests.test_rendering --keepdb -v 2`
Expected: FAIL — `AttributeError: module 'messaging.rendering' has no attribute 'render_text'`.

- [ ] **Step 3: Rewrite the renderer**

Replace the entire contents of `brandtechsolution/messaging/rendering.py` with:
```python
import html as html_lib
import re

from django.utils.html import escape

from .placeholders import PLACEHOLDER_RE


def _substitute(template_str, context, escape_values):
    """Replace {{ key }} with context[key]; unknown keys render as empty string."""

    def replace(match):
        value = context.get(match.group(1), "")
        return escape(value) if escape_values else value

    return PLACEHOLDER_RE.sub(replace, template_str or "")


def render_text(template_str, context):
    """Render for a plain-text context (subject line, text alternative)."""
    return _substitute(template_str, context, escape_values=False)


def render_html(template_str, context):
    """Render for an HTML context; values are HTML-escaped."""
    return _substitute(template_str, context, escape_values=True)


def html_to_text(html):
    """Very small HTML-to-text conversion for the plain-text alternative."""
    text = re.sub(r"<[^>]+>", "", html or "")
    text = html_lib.unescape(text)
    return re.sub(r"[ \t]+", " ", text)
```

Note: `escape()` returns a `SafeString`; `PLACEHOLDER_RE.sub` coerces it to `str`, so the return type stays a plain string.

- [ ] **Step 4: Update the send command imports**

In `brandtechsolution/messaging/management/commands/process_email_outbox.py`, replace line 13:
```python
from messaging.rendering import render_body, render_subject, html_to_text
```
with:
```python
from messaging.placeholders import build_context
from messaging.rendering import html_to_text, render_html, render_text
```

- [ ] **Step 5: Update the send-command call site**

In the same file, in `_send_one`, replace these two lines (currently lines 147-148):
```python
        subject = render_subject(campaign.subject, recipient.name)
        html_body = render_body(campaign.body_html, recipient.name, unsubscribe_url)
```
with:
```python
        context = build_context(recipient, unsubscribe_url)
        subject = render_text(campaign.subject, context)
        html_body = render_html(campaign.body_html, context)
```
Leave every other line of `_send_one` unchanged — the unsubscribe footer append, `List-Unsubscribe` headers, plain-text fallback, and error handling all stay exactly as they are.

- [ ] **Step 6: Run the full messaging suite**

Run: `./.venv/bin/python manage.py test messaging --keepdb -v 2`
Expected: PASS. The rendering tests are new/rewritten; the 67 pre-existing tests (including the whole send-engine suite) must still pass.

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/messaging/rendering.py brandtechsolution/messaging/tests/test_rendering.py brandtechsolution/messaging/management/commands/process_email_outbox.py
git commit -m "feat(messaging): context-driven renderer with HTML escaping

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Email HTML pipeline (sanitize + inline)

**Files:**
- Create: `brandtechsolution/messaging/emailhtml.py`
- Modify: `brandtechsolution/requirements.txt` (add `css-inline`)
- Create: `brandtechsolution/messaging/tests/test_emailhtml.py`

**Interfaces:**
- Produces:
  - `sanitize_email_html(html) -> str`
  - `inline_email_css(html) -> str`
  - `ALLOWED_TAGS: set[str]`, `ALLOWED_ATTRIBUTES: dict`, `BASE_EMAIL_CSS: str`

**Library notes (verified):** `nh3.clean(html, tags=..., attributes=...)` keeps `style`, strips `<script>` and `onclick`, and adds `rel="noopener noreferrer"` to links. `css_inline.inline_fragment(html, css)` inlines a **fragment** (no document wrapper, no `<style>` block to strip).

- [ ] **Step 1: Install the dependency**

Add `css-inline` to `brandtechsolution/requirements.txt` (unpinned, matching the file's existing style), then:
Run: `./.venv/bin/pip install css-inline`

- [ ] **Step 2: Write the failing test**

Create `brandtechsolution/messaging/tests/test_emailhtml.py`:
```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./.venv/bin/python manage.py test messaging.tests.test_emailhtml --keepdb -v 2`
Expected: FAIL — `ImportError: cannot import name 'emailhtml'`.

- [ ] **Step 4: Write the implementation**

Create `brandtechsolution/messaging/emailhtml.py`:
```python
"""Prepare authored HTML for delivery to email clients.

Two stages, both applied when a template or campaign body is saved:

1. sanitize_email_html - strip anything unsafe, keep email-safe markup.
2. inline_email_css    - inline BASE_EMAIL_CSS, because Outlook and Gmail
                         ignore <style> blocks and external CSS classes.

The sanitized (non-inlined) result is stored as `body_source` for editing;
the inlined result is stored as `body_html` and is what gets sent.
"""
import css_inline
import nh3

ALLOWED_TAGS = {
    "p", "br", "hr", "span", "div",
    "strong", "b", "em", "i", "u",
    "a", "img",
    "ul", "ol", "li",
    "h1", "h2", "h3", "h4",
    "blockquote",
    "table", "thead", "tbody", "tr", "td", "th",
}

ALLOWED_ATTRIBUTES = {
    "*": {"style", "class"},
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "align", "valign"},
    "th": {"colspan", "rowspan", "align", "valign"},
}

BASE_EMAIL_CSS = """
p, li, td, th, blockquote {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: #1f2937;
}
h1, h2, h3, h4 {
    font-family: Arial, Helvetica, sans-serif;
    color: #111827;
    margin: 0 0 12px 0;
}
h1 { font-size: 26px; }
h2 { font-size: 22px; }
h3 { font-size: 18px; }
h4 { font-size: 16px; }
p { margin: 0 0 14px 0; }
a { color: #007AFF; text-decoration: underline; }
ul, ol { margin: 0 0 14px 24px; padding: 0; }
blockquote {
    margin: 0 0 14px 0;
    padding: 8px 14px;
    border-left: 3px solid #d1d5db;
    color: #4b5563;
}
img { max-width: 100%; height: auto; }
hr { border: 0; border-top: 1px solid #e5e7eb; margin: 20px 0; }
"""


def sanitize_email_html(html):
    """Strip unsafe markup, keeping email-safe tags and the style attribute."""
    if not html:
        return ""
    return nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)


def inline_email_css(html):
    """Inline BASE_EMAIL_CSS so styling survives email clients."""
    if not html:
        return ""
    return css_inline.inline_fragment(html, BASE_EMAIL_CSS)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/bin/python manage.py test messaging.tests.test_emailhtml --keepdb -v 2`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/messaging/emailhtml.py brandtechsolution/messaging/tests/test_emailhtml.py brandtechsolution/requirements.txt
git commit -m "feat(messaging): sanitize and CSS-inline email bodies

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `body_source` fields, migration, and serializer derivation

**Files:**
- Modify: `brandtechsolution/messaging/models.py` (`EmailTemplate`, `Campaign`)
- Create: migration via `makemigrations` + a hand-written data migration
- Modify: `brandtechsolution/messaging/serializers.py`
- Create: `brandtechsolution/messaging/tests/test_body_source.py`

**Interfaces:**
- Consumes: `sanitize_email_html`, `inline_email_css` (Task 3)
- Produces:
  - `EmailTemplate.body_source` and `Campaign.body_source` (`TextField`, `blank=True`, `default=""`)
  - `EmailBodyMixin` in `serializers.py` — sanitizes `body_source` on input and derives `body_html`
  - API contract: `body_source` writable, `body_html` read-only

- [ ] **Step 1: Write the failing test**

Create `brandtechsolution/messaging/tests/test_body_source.py`:
```python
from django.contrib.auth.models import User
from django.test import TestCase

from messaging.models import Campaign, EmailTemplate


class BodySourceApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.client.force_login(self.staff)

    def test_template_stores_source_and_derives_inlined_html(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "Welcome", "subject": "Hi", "body_source": "<p>Hello</p>",
        })
        self.assertEqual(resp.status_code, 201)
        tpl = EmailTemplate.objects.get()
        self.assertEqual(tpl.body_source, "<p>Hello</p>")
        self.assertIn("style=", tpl.body_html)

    def test_body_html_is_read_only(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s",
            "body_source": "<p>real</p>", "body_html": "<p>ignored</p>",
        })
        self.assertEqual(resp.status_code, 201)
        tpl = EmailTemplate.objects.get()
        self.assertNotIn("ignored", tpl.body_html)
        self.assertIn("real", tpl.body_html)

    def test_source_is_sanitized_on_save(self):
        self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s",
            "body_source": "<p>ok</p><script>alert(1)</script>",
        })
        tpl = EmailTemplate.objects.get()
        self.assertNotIn("script", tpl.body_source)
        self.assertNotIn("script", tpl.body_html)

    def test_edit_round_trip_leaves_source_stable(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "T", "subject": "s", "body_source": "<p>Hello</p>",
        })
        tpl_id = resp.json()["id"]
        first_source = EmailTemplate.objects.get(id=tpl_id).body_source
        # Re-save exactly what the editor would send back.
        self.client.put(
            f"/api/messaging/templates/{tpl_id}/",
            data={"name": "T", "subject": "s", "body_source": first_source},
            content_type="application/json",
        )
        second_source = EmailTemplate.objects.get(id=tpl_id).body_source
        self.assertEqual(first_source, second_source)
        self.assertNotIn("style=", second_source)

    def test_campaign_also_derives_body_html(self):
        resp = self.client.post("/api/messaging/campaigns/", data={
            "name": "C", "subject": "s", "body_source": "<p>Hi</p>",
        })
        self.assertEqual(resp.status_code, 201)
        campaign = Campaign.objects.get()
        self.assertEqual(campaign.body_source, "<p>Hi</p>")
        self.assertIn("style=", campaign.body_html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python manage.py test messaging.tests.test_body_source --keepdb -v 2`
Expected: FAIL — `body_source` is not a model field / not accepted by the serializer.

- [ ] **Step 3: Add the model fields**

In `brandtechsolution/messaging/models.py`, add to `EmailTemplate`, immediately after the `subject` field:
```python
    body_source = models.TextField(
        blank=True,
        default="",
        help_text="Authored HTML as edited. Sanitized but not CSS-inlined.",
    )
```
And add the identical field to `Campaign`, immediately after its `subject` field:
```python
    body_source = models.TextField(
        blank=True,
        default="",
        help_text="Authored HTML as edited. Sanitized but not CSS-inlined.",
    )
```
Leave both `body_html` fields exactly as they are.

- [ ] **Step 4: Generate the schema migration**

Run: `./.venv/bin/python manage.py makemigrations messaging`
Expected: creates a migration adding `body_source` to both models. Note its filename (e.g. `0007_...`).

- [ ] **Step 5: Add the data migration backfilling source from existing HTML**

Run: `./.venv/bin/python manage.py makemigrations messaging --empty --name backfill_body_source`
Then replace the generated file's contents with (adjusting the dependency to the migration created in Step 4):
```python
from django.db import migrations


def backfill_body_source(apps, schema_editor):
    """Existing rows hold un-inlined authored HTML, so it is a valid source."""
    for model_name in ("EmailTemplate", "Campaign"):
        model = apps.get_model("messaging", model_name)
        for obj in model.objects.exclude(body_html="").filter(body_source=""):
            obj.body_source = obj.body_html
            obj.save(update_fields=["body_source"])


def noop_reverse(apps, schema_editor):
    """Reversing drops nothing: body_source is additive."""


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "REPLACE_WITH_STEP_4_MIGRATION_NAME"),
    ]

    operations = [
        migrations.RunPython(backfill_body_source, noop_reverse),
    ]
```
Replace `REPLACE_WITH_STEP_4_MIGRATION_NAME` with the actual migration name from Step 4 (e.g. `0007_emailtemplate_body_source_campaign_body_source`). Do not leave the placeholder string in the file.

- [ ] **Step 6: Update the serializers**

Replace the contents of `brandtechsolution/messaging/serializers.py` with:
```python
from rest_framework import serializers

from .emailhtml import inline_email_css, sanitize_email_html
from .models import Campaign, EmailTemplate, Inquiry


class InquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = ["id", "name", "email", "phone", "message", "status", "created_at"]
        read_only_fields = ["id", "name", "email", "phone", "message", "created_at"]


class EmailBodyMixin:
    """Sanitize the authored body and derive the inlined body sent to recipients.

    Clients submit `body_source`; `body_html` is always derived, never accepted.
    """

    def validate_body_source(self, value):
        return sanitize_email_html(value)

    def _with_derived_body(self, validated_data):
        if "body_source" in validated_data:
            validated_data["body_html"] = inline_email_css(validated_data["body_source"])
        return validated_data

    def create(self, validated_data):
        return super().create(self._with_derived_body(validated_data))

    def update(self, instance, validated_data):
        return super().update(instance, self._with_derived_body(validated_data))


class EmailTemplateSerializer(EmailBodyMixin, serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = [
            "id", "name", "subject", "body_source", "body_html",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "body_html", "created_at", "updated_at"]


class CampaignSerializer(EmailBodyMixin, serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "id", "name", "subject", "body_source", "body_html", "template", "status",
            "total", "sent_count", "failed_count",
            "created_at", "started_at", "completed_at",
        ]
        read_only_fields = [
            "id", "body_html", "status", "total", "sent_count", "failed_count",
            "created_at", "started_at", "completed_at",
        ]
```

- [ ] **Step 7: Run the full messaging suite**

Run: `./.venv/bin/python manage.py test messaging --keepdb -v 2`
Expected: PASS, including the new `test_body_source` tests.
Note: existing tests that create campaigns directly via `Campaign.objects.create(... body_html=...)` keep working — the model still accepts `body_html`; only the API makes it read-only.

- [ ] **Step 8: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): store body_source and derive inlined body_html

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Placeholders and preview endpoints

**Files:**
- Modify: `brandtechsolution/messaging/api.py`
- Modify: `brandtechsolution/messaging/api_urls.py`
- Create: `brandtechsolution/messaging/tests/test_preview_api.py`

**Interfaces:**
- Consumes: `PLACEHOLDERS`, `sample_context`, `unknown_placeholders` (Task 1); `render_text`, `render_html` (Task 2); `sanitize_email_html`, `inline_email_css` (Task 3)
- Produces:
  - `GET /api/messaging/placeholders/` → `[{key, label, description, sample}, ...]`
  - `POST /api/messaging/preview/` with `{subject, body_source}` → `{subject, body_html, unknown}`
  - Both staff-only.

- [ ] **Step 1: Write the failing test**

Create `brandtechsolution/messaging/tests/test_preview_api.py`:
```python
from django.contrib.auth.models import User
from django.test import TestCase


class PlaceholderApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def test_anonymous_denied(self):
        self.assertIn(
            self.client.get("/api/messaging/placeholders/").status_code, (401, 403)
        )

    def test_staff_gets_registry(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/api/messaging/placeholders/")
        self.assertEqual(resp.status_code, 200)
        keys = {entry["key"] for entry in resp.json()}
        self.assertIn("first_name", keys)
        self.assertIn("unsubscribe_url", keys)
        for entry in resp.json():
            self.assertIn("label", entry)
            self.assertIn("description", entry)


class PreviewApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def test_anonymous_denied(self):
        resp = self.client.post(
            "/api/messaging/preview/",
            data={"subject": "s", "body_source": "<p>x</p>"},
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (401, 403))

    def _preview(self, subject, body_source):
        self.client.force_login(self.staff)
        return self.client.post(
            "/api/messaging/preview/",
            data={"subject": subject, "body_source": body_source},
            content_type="application/json",
        )

    def test_renders_sample_values_and_inlines_css(self):
        resp = self._preview("Hi {{ first_name }}", "<p>Hello {{ first_name }}</p>")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["subject"], "Hi Ada")
        self.assertIn("Hello Ada", data["body_html"])
        self.assertIn("style=", data["body_html"])

    def test_reports_unknown_placeholders_from_subject_and_body(self):
        resp = self._preview("{{ nope }}", "<p>{{ alsonope }} {{ name }}</p>")
        self.assertEqual(sorted(resp.json()["unknown"]), ["alsonope", "nope"])

    def test_sanitizes_before_rendering(self):
        resp = self._preview("s", "<p>ok</p><script>alert(1)</script>")
        self.assertNotIn("script", resp.json()["body_html"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python manage.py test messaging.tests.test_preview_api --keepdb -v 2`
Expected: FAIL — 404, routes do not exist.

- [ ] **Step 3: Add the endpoints**

Append to `brandtechsolution/messaging/api.py`:
```python
from .emailhtml import inline_email_css, sanitize_email_html
from .placeholders import PLACEHOLDERS, sample_context, unknown_placeholders
from .rendering import render_html, render_text


@api_view(["GET"])
@permission_classes([IsAdminUser])
def placeholders(request):
    """Registry that drives the editor's insert-placeholder menu."""
    return Response(PLACEHOLDERS)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def preview(request):
    """Render a draft exactly the way the sender will, using sample values."""
    subject_source = request.data.get("subject") or ""
    body_source = request.data.get("body_source") or ""

    context = sample_context()
    prepared_html = inline_email_css(sanitize_email_html(body_source))

    unknown = []
    for text in (subject_source, body_source):
        for key in unknown_placeholders(text):
            if key not in unknown:
                unknown.append(key)

    return Response({
        "subject": render_text(subject_source, context),
        "body_html": render_html(prepared_html, context),
        "unknown": unknown,
    })
```

- [ ] **Step 4: Add the routes**

In `brandtechsolution/messaging/api_urls.py`, add to `urlpatterns` alongside the existing `extract-emails/` route:
```python
    path("placeholders/", api.placeholders, name="placeholders"),
    path("preview/", api.preview, name="preview"),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/bin/python manage.py test messaging.tests.test_preview_api --keepdb -v 2`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): placeholders registry and preview endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Editor module + Templates section wiring

**Files:**
- Create: `brandtechsolution/brand/static/brand/js/admin/editor.js`
- Modify: `brandtechsolution/brand/templates/brand/admin/_templates.html`
- Modify: `brandtechsolution/brand/static/brand/js/admin/templates.js`
- Modify: `brandtechsolution/brand/templates/brand/admin_panel.html` (Quill CDN assets + editor.js script tag)
- Modify: `brandtechsolution/messaging/tests/test_admin_panel_render.py`

**Interfaces:**
- Consumes: `GET /api/messaging/placeholders/`, `POST /api/messaging/preview/` (Task 5); `escapeHtml`, `API_BASE`, `CSRF_TOKEN` from `core.js`
- Produces (globals on `window`):
  - `createEmailEditor(prefix) -> editor` where `editor` has `getValue()`, `setValue(html)`, `toggleSource()`, `insertPlaceholder(key)`, `preview()`
  - `getEmailEditor(prefix) -> editor | undefined`

**Element id convention:** for a given `prefix` (`template` or `campaign`), the markup provides
`<prefix>EditorContainer`, `<prefix>SourceTextarea`, `<prefix>SourceToggle`, `<prefix>PlaceholderMenu`, `<prefix>SubjectInput`, `<prefix>SubjectPlaceholderMenu`, `<prefix>PreviewBtn`, `<prefix>PreviewFrame`, `<prefix>UnknownWarning`.

- [ ] **Step 1: Extend the render test**

In `brandtechsolution/messaging/tests/test_admin_panel_render.py`, add these ids to the asserted anchors list used by the staff-render test:
```python
            'id="templateEditorContainer"',
            'id="templateSourceToggle"',
            'id="templatePreviewFrame"',
```
and assert the editor asset is loaded by adding `'editor.js'` to the asserted script list.

Run: `./.venv/bin/python manage.py test messaging.tests.test_admin_panel_render --keepdb -v 2`
Expected: FAIL — those ids are absent.

- [ ] **Step 2a: Compute Subresource Integrity hashes for Quill**

The admin panel is a privileged staff context with access to the bulk-mail API, so a compromised CDN must not be able to inject script into it. Pin both Quill assets with SRI.

Run:
```bash
for f in quill.js quill.snow.css; do
  printf '%s: sha384-' "$f"
  curl -sL "https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/$f" \
    | openssl dgst -sha384 -binary | openssl base64 -A
  echo
done
```
Record both values; you will paste them into the tags in Step 2b.

If the machine has no network access, **self-host instead**: download the two files into `brandtechsolution/brand/static/brand/vendor/quill/` and reference them with `{% static %}` rather than a CDN URL. Self-hosting removes the CDN trust dependency entirely and is the stronger option — take it if vendoring ~200KB is acceptable. Do NOT ship CDN tags without integrity attributes.

- [ ] **Step 2b: Add Quill assets to the panel shell**

In `brandtechsolution/brand/templates/brand/admin_panel.html`, inside `<head>` after the FontAwesome stylesheet link, add (substituting the two hashes from Step 2a):
```html
    <!-- Quill (email body editor) -->
    <link href="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css" rel="stylesheet"
        integrity="sha384-REPLACE_WITH_CSS_HASH" crossorigin="anonymous" referrerpolicy="no-referrer">
    <script src="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js"
        integrity="sha384-REPLACE_WITH_JS_HASH" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
    <style>
        .ql-toolbar.ql-snow, .ql-container.ql-snow { border-color: rgba(255,255,255,0.08); }
        .ql-toolbar.ql-snow .ql-stroke { stroke: #9ca3af; }
        .ql-toolbar.ql-snow .ql-fill { fill: #9ca3af; }
        .ql-toolbar.ql-snow .ql-picker-label { color: #9ca3af; }
        .ql-editor { background: #06090F; color: #e5e7eb; min-height: 220px; }
        .ql-editor.ql-blank::before { color: #6b7280; }
    </style>
```
And before `</body>`, add the editor script **after** `core.js` and before the section modules:
```html
<script src="{% static 'brand/js/admin/editor.js' %}" defer></script>
```

- [ ] **Step 3: Write the editor module**

Create `brandtechsolution/brand/static/brand/js/admin/editor.js`:
```javascript
// Shared email-body editor: Quill with an email-safe toolbar, placeholder
// insertion, a raw-HTML source toggle, and server-rendered preview.
// Alignment and indentation are deliberately excluded: Quill implements them
// with CSS classes that email clients discard.

const EMAIL_TOOLBAR = [
    ['bold', 'italic', 'underline'],
    [{ header: [2, 3, false] }],
    ['link', 'blockquote'],
    [{ list: 'ordered' }, { list: 'bullet' }],
    ['clean'],
];

let PLACEHOLDER_CACHE = null;
const EMAIL_EDITORS = {};

async function loadPlaceholderRegistry() {
    if (PLACEHOLDER_CACHE) return PLACEHOLDER_CACHE;
    const res = await fetch(`${API_BASE}/messaging/placeholders/`, { credentials: 'same-origin' });
    PLACEHOLDER_CACHE = res.ok ? await res.json() : [];
    return PLACEHOLDER_CACHE;
}

function renderPlaceholderMenu(menuEl, onPick) {
    if (!menuEl) return;
    loadPlaceholderRegistry().then(entries => {
        menuEl.innerHTML =
            `<option value="">Insert placeholder…</option>` +
            entries.map(e =>
                `<option value="${escapeHtml(e.key)}" title="${escapeHtml(e.description)}">${escapeHtml(e.label)}</option>`
            ).join('');
        menuEl.onchange = () => {
            if (menuEl.value) { onPick(menuEl.value); menuEl.value = ''; }
        };
    });
}

function insertAtCaret(input, text) {
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    input.value = input.value.slice(0, start) + text + input.value.slice(end);
    const pos = start + text.length;
    input.setSelectionRange(pos, pos);
    input.focus();
}

function createEmailEditor(prefix) {
    const container = document.getElementById(`${prefix}EditorContainer`);
    if (!container) return undefined;

    const textarea = document.getElementById(`${prefix}SourceTextarea`);
    const toggleBtn = document.getElementById(`${prefix}SourceToggle`);
    const previewBtn = document.getElementById(`${prefix}PreviewBtn`);
    const frame = document.getElementById(`${prefix}PreviewFrame`);
    const warning = document.getElementById(`${prefix}UnknownWarning`);
    const subjectInput = document.getElementById(`${prefix}SubjectInput`);

    const quill = new Quill(container, {
        theme: 'snow',
        modules: { toolbar: EMAIL_TOOLBAR },
        placeholder: 'Write your email…',
    });

    let sourceMode = false;

    const editor = {
        getValue() {
            return sourceMode ? textarea.value : quill.root.innerHTML;
        },
        setValue(html) {
            const value = html || '';
            textarea.value = value;
            quill.root.innerHTML = value;
        },
        toggleSource() {
            if (sourceMode) {
                // Source -> visual. Quill may normalise markup it cannot model.
                if (!confirm('Switch back to the visual editor? It may simplify HTML it does not support.')) return;
                quill.root.innerHTML = textarea.value;
                textarea.classList.add('hidden');
                container.classList.remove('hidden');
                document.querySelector(`#${prefix}EditorWrap .ql-toolbar`)?.classList.remove('hidden');
                toggleBtn.textContent = 'Source';
            } else {
                textarea.value = quill.root.innerHTML;
                container.classList.add('hidden');
                document.querySelector(`#${prefix}EditorWrap .ql-toolbar`)?.classList.add('hidden');
                textarea.classList.remove('hidden');
                toggleBtn.textContent = 'Visual';
            }
            sourceMode = !sourceMode;
        },
        insertPlaceholder(key) {
            const token = `{{ ${key} }}`;
            if (sourceMode) { insertAtCaret(textarea, token); return; }
            const range = quill.getSelection(true);
            quill.insertText(range ? range.index : quill.getLength(), token, 'user');
        },
        async preview() {
            const res = await fetch(`${API_BASE}/messaging/preview/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
                body: JSON.stringify({
                    subject: subjectInput ? subjectInput.value : '',
                    body_source: editor.getValue(),
                }),
            });
            if (!res.ok) { alert('Preview failed'); return; }
            const data = await res.json();
            if (frame) {
                frame.classList.remove('hidden');
                frame.srcdoc =
                    `<html><body style="margin:0;padding:16px;background:#ffffff;">` +
                    `<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#6b7280;margin-bottom:12px;">` +
                    `Subject: ${escapeHtml(data.subject)}</div>${data.body_html}</body></html>`;
            }
            if (warning) {
                if (data.unknown && data.unknown.length) {
                    warning.classList.remove('hidden');
                    warning.innerHTML =
                        `Unknown placeholder(s): ${data.unknown.map(k => escapeHtml(k)).join(', ')} — these render empty.`;
                } else {
                    warning.classList.add('hidden');
                    warning.innerHTML = '';
                }
            }
        },
    };

    if (toggleBtn) toggleBtn.onclick = () => editor.toggleSource();
    if (previewBtn) previewBtn.onclick = () => editor.preview();
    renderPlaceholderMenu(
        document.getElementById(`${prefix}PlaceholderMenu`),
        key => editor.insertPlaceholder(key),
    );
    if (subjectInput) {
        renderPlaceholderMenu(
            document.getElementById(`${prefix}SubjectPlaceholderMenu`),
            key => insertAtCaret(subjectInput, `{{ ${key} }}`),
        );
    }

    EMAIL_EDITORS[prefix] = editor;
    return editor;
}

function getEmailEditor(prefix) {
    return EMAIL_EDITORS[prefix];
}
```

- [ ] **Step 4: Replace the body field in the Templates partial**

In `brandtechsolution/brand/templates/brand/admin/_templates.html`, replace the existing HTML-body form group (the `<label>` + `<textarea name="body_html">` block) with:
```html
            <div>
                <div class="flex items-center justify-between mb-2 gap-2">
                    <label class="block text-sm font-medium text-gray-400">Email body</label>
                    <div class="flex items-center gap-2">
                        <select id="templatePlaceholderMenu"
                            class="bg-[#06090F] border border-dark-border rounded px-2 py-1 text-xs text-gray-300"></select>
                        <button type="button" id="templateSourceToggle"
                            class="px-3 py-1 text-xs rounded border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Source</button>
                        <button type="button" id="templatePreviewBtn"
                            class="px-3 py-1 text-xs rounded border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Preview</button>
                    </div>
                </div>
                <div id="templateEditorWrap">
                    <div id="templateEditorContainer"></div>
                    <textarea id="templateSourceTextarea" rows="12"
                        class="hidden w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white font-mono text-sm focus:outline-none focus:border-brand-blue"></textarea>
                </div>
                <div id="templateUnknownWarning"
                    class="hidden mt-2 text-xs text-yellow-400 bg-yellow-900/20 border border-yellow-900/40 rounded px-3 py-2"></div>
                <iframe id="templatePreviewFrame" title="Email preview"
                    class="hidden w-full h-80 mt-3 rounded-lg border border-dark-border bg-white" sandbox=""></iframe>
            </div>
```
Also give the existing subject input the id `templateSubjectInput` and add a subject placeholder menu directly after it:
```html
                <select id="templateSubjectPlaceholderMenu"
                    class="mt-2 bg-[#06090F] border border-dark-border rounded px-2 py-1 text-xs text-gray-300"></select>
```

- [ ] **Step 5: Wire the Templates JS to the editor**

In `brandtechsolution/brand/static/brand/js/admin/templates.js`:

Replace the body handling in `saveTemplate` so the payload uses `body_source` from the editor:
```javascript
    const editor = getEmailEditor('template');
    const payload = {
        name: form.name.value,
        subject: form.subject.value,
        body_source: editor ? editor.getValue() : '',
    };
```
In `editTemplate`, load the **source** (never the inlined HTML) into the editor:
```javascript
    const editor = getEmailEditor('template');
    if (editor) editor.setValue(t.body_source || '');
```
and remove any line that assigned `form.body_html.value`.

In `loadTemplates`, after rendering the list, ensure the editor exists:
```javascript
    if (!getEmailEditor('template')) createEmailEditor('template');
```
Keep `escapeHtml(...)` on `t.name` and `t.subject` exactly as it is — do not regress the XSS fix.

- [ ] **Step 6: Verify**

Run: `./.venv/bin/python manage.py test messaging.tests.test_admin_panel_render --keepdb -v 2`
Expected: PASS.
Run: `node --check brandtechsolution/brand/static/brand/js/admin/editor.js` and `node --check brandtechsolution/brand/static/brand/js/admin/templates.js`
Expected: no output (both parse).
Then confirm every function referenced by an `onclick`/`onchange` in the new markup is defined:
Run: `grep -nE "createEmailEditor|getEmailEditor" brandtechsolution/brand/static/brand/js/admin/*.js`
Expected: definitions in `editor.js`, uses in `templates.js`.

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/brand brandtechsolution/messaging/tests/test_admin_panel_render.py
git commit -m "feat(admin-panel): Quill email editor with placeholders and preview

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Campaigns section wiring

**Files:**
- Modify: `brandtechsolution/brand/templates/brand/admin/_campaigns.html`
- Modify: `brandtechsolution/brand/static/brand/js/admin/campaigns.js`
- Modify: `brandtechsolution/messaging/tests/test_admin_panel_render.py`

**Interfaces:**
- Consumes: `createEmailEditor(prefix)`, `getEmailEditor(prefix)` (Task 6); `body_source` API contract (Task 4)

- [ ] **Step 1: Extend the render test**

In `brandtechsolution/messaging/tests/test_admin_panel_render.py`, add to the asserted anchors:
```python
            'id="campaignEditorContainer"',
            'id="campaignPreviewFrame"',
```
Run: `./.venv/bin/python manage.py test messaging.tests.test_admin_panel_render --keepdb -v 2`
Expected: FAIL — ids absent.

- [ ] **Step 2: Replace the body field in the Campaigns partial**

In `brandtechsolution/brand/templates/brand/admin/_campaigns.html`, replace the existing HTML-body form group (the `<label>` + `<textarea name="body_html">` block) with:
```html
            <div>
                <div class="flex items-center justify-between mb-2 gap-2">
                    <label class="block text-sm font-medium text-gray-400">Email body</label>
                    <div class="flex items-center gap-2">
                        <select id="campaignPlaceholderMenu"
                            class="bg-[#06090F] border border-dark-border rounded px-2 py-1 text-xs text-gray-300"></select>
                        <button type="button" id="campaignSourceToggle"
                            class="px-3 py-1 text-xs rounded border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Source</button>
                        <button type="button" id="campaignPreviewBtn"
                            class="px-3 py-1 text-xs rounded border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Preview</button>
                    </div>
                </div>
                <div id="campaignEditorWrap">
                    <div id="campaignEditorContainer"></div>
                    <textarea id="campaignSourceTextarea" rows="12"
                        class="hidden w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white font-mono text-sm focus:outline-none focus:border-brand-blue"></textarea>
                </div>
                <div id="campaignUnknownWarning"
                    class="hidden mt-2 text-xs text-yellow-400 bg-yellow-900/20 border border-yellow-900/40 rounded px-3 py-2"></div>
                <iframe id="campaignPreviewFrame" title="Email preview"
                    class="hidden w-full h-80 mt-3 rounded-lg border border-dark-border bg-white" sandbox=""></iframe>
            </div>
```
Give the campaign subject input the id `campaignSubjectInput` and add after it:
```html
                <select id="campaignSubjectPlaceholderMenu"
                    class="mt-2 bg-[#06090F] border border-dark-border rounded px-2 py-1 text-xs text-gray-300"></select>
```

- [ ] **Step 3: Wire the Campaigns JS**

In `brandtechsolution/brand/static/brand/js/admin/campaigns.js`:

In `createCampaign`, send `body_source` from the editor:
```javascript
    const editor = getEmailEditor('campaign');
    const payload = {
        name: form.name.value,
        subject: form.subject.value,
        body_source: editor ? editor.getValue() : '',
    };
```
In `applyTemplate`, copy the template's **source** into the editor (the server re-derives the inlined body):
```javascript
function applyTemplate() {
    const id = document.getElementById('campaignTemplate').value;
    const t = TEMPLATE_CACHE.find(x => String(x.id) === String(id));
    const form = document.getElementById('addCampaignForm');
    if (!t) return;
    form.subject.value = t.subject;
    const editor = getEmailEditor('campaign');
    if (editor) editor.setValue(t.body_source || '');
}
```
In `loadCampaigns`, ensure the editor exists:
```javascript
    if (!getEmailEditor('campaign')) createEmailEditor('campaign');
```
Keep `escapeHtml(...)` on `c.name`, `c.subject`, `c.status`, and `t.name` exactly as-is.

- [ ] **Step 4: Verify**

Run: `./.venv/bin/python manage.py test messaging --keepdb -v 2`
Expected: PASS (all tests).
Run: `node --check brandtechsolution/brand/static/brand/js/admin/campaigns.js`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add brandtechsolution/brand brandtechsolution/messaging/tests/test_admin_panel_render.py
git commit -m "feat(admin-panel): campaign body editor with template source seeding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Full regression and documentation

**Files:**
- Modify: `README.md` (placeholder reference)

- [ ] **Step 1: Confirm no missing migrations**

Run: `./.venv/bin/python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 2: Run the messaging suite**

Run: `./.venv/bin/python manage.py test messaging --keepdb -v 2`
Expected: all pass, output pristine.

- [ ] **Step 3: Run the full project suite**

Run: `./.venv/bin/python manage.py test --keepdb -v 0`
Expected: the only failures are the pre-existing ones in the `brand` app (9 failures + 17 errors at the time of writing — DB index assertions unrelated to messaging). Report the counts; any NEW failure must be fixed.

- [ ] **Step 4: Document the placeholders**

Add a short "Email placeholders" subsection to the Bulk email section of `README.md`:
```markdown
### Email placeholders

Templates and campaigns support these merge fields in both the subject and body:

| Placeholder | Renders as |
|---|---|
| `{{ name }}` | Recipient's full name (may be blank) |
| `{{ first_name }}` | First word of the recipient's name |
| `{{ email }}` | Recipient's email address |
| `{{ date }}` | Send date, e.g. July 19, 2026 |
| `{{ year }}` | Send year |
| `{{ unsubscribe_url }}` | Per-recipient unsubscribe link (appended automatically if omitted) |

Unknown placeholders render as empty text; the editor warns about them before
you save. The editor stores what you author as `body_source` and derives the
CSS-inlined `body_html` that is actually sent, so editing is lossless.
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document email placeholders

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Placeholder registry as single source of truth (spec §1) → Task 1. ✓
- `build_context` with injectable `now` and `extra` hook for sub-project 2 (§1) → Task 1. ✓
- Renderer with HTML escaping, unknown→empty, subject/body parity (§2) → Task 2. ✓
- Send-command call-site update (§2) → Task 2 Steps 4-5. ✓
- `sanitize_email_html` + `inline_email_css` + `BASE_EMAIL_CSS` (§3) → Task 3. ✓
- `body_source` / `body_html` split, migration + backfill, serializer derivation, `body_html` read-only (§3) → Task 4. ✓
- Quill with email-safe toolbar, insert-placeholder, Source toggle (§4) → Task 6. ✓
- `placeholders` + `preview` endpoints, staff-only, sandboxed iframe (§5) → Tasks 5, 6. ✓
- Editing loads `body_source`; `applyTemplate` copies source (§6) → Tasks 6, 7. ✓
- Testing requirements (§7) → covered per task; regression in Task 8. ✓

**Placeholder scan:** No TBD/TODO. Every code step contains complete code. Two intentional fill-ins exist, both with an explicit command or instruction for producing the real value, and both stated as must-not-ship-as-written: the data-migration `dependencies` entry (Task 4 Step 5, unknowable before `makemigrations` runs) and the two SRI hashes (Task 6 Step 2a, produced by the given `curl | openssl` command).

**Security note:** external editor assets are pinned with Subresource Integrity and `crossorigin="anonymous"`, because the admin panel is a privileged staff context — an unpinned CDN script there would be equivalent to the stored-XSS hole already fixed in this codebase. Self-hosting is offered as the stronger alternative.

**Type/name consistency:** `PLACEHOLDER_RE` defined in Task 1, imported by Task 2. `build_context`/`sample_context`/`unknown_placeholders` (Task 1) used in Tasks 2 and 5. `render_text`/`render_html`/`html_to_text` (Task 2) used in Tasks 2 and 5. `sanitize_email_html`/`inline_email_css` (Task 3) used in Tasks 4 and 5. `body_source` field name consistent across Tasks 4, 5, 6, 7. `createEmailEditor`/`getEmailEditor` defined in Task 6, used in Tasks 6 and 7. Element-id prefix convention (`template`/`campaign`) matches the ids in the Task 6 and 7 markup.

**Scope:** One cohesive sub-project (authoring), 8 tasks, each independently testable. Recipient data & quality (custom CSV columns, MX validation, recipient list management) remains deferred to its own spec.
