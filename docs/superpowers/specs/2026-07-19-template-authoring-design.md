# Template Authoring: Placeholders, WYSIWYG Editor, Preview — Design

**Date:** 2026-07-19
**Status:** Approved (design), pending implementation plan
**Scope:** Sub-project 1 of 2. Covers how an email is *authored*. Sub-project 2 (recipient data & quality: per-recipient custom fields from CSV columns, email validation with MX checks, recipient list view/remove/add) is explicitly deferred to its own spec.

## Summary

The admin panel's Templates and Campaigns sections currently expose a bare `<textarea>` for raw HTML, and placeholder support is two hardcoded `str.replace` calls. This work replaces both: a real placeholder engine driven by a single registry, a restricted WYSIWYG editor whose output is sanitized and CSS-inlined for email clients, an insert-placeholder control, and a true-fidelity server-rendered preview.

## Context & constraints

- **Per-recipient data is limited to `email` and `name`.** `CampaignRecipient` stores nothing else, so the core placeholder set is bounded by that plus send-time values (date/year) and the generated unsubscribe URL. Richer merge fields require sub-project 2.
- **Current placeholder handling is inconsistent and unsafe.** `render_subject()` supports only `{{ name }}`; `render_body()` supports `{{ name }}` and `{{ unsubscribe_url }}`. Neither escapes values, so a recipient named `Ben & Jerry` injects a raw `&` into HTML.
- **Email HTML is not web HTML.** Outlook/Gmail ignore `<style>` blocks and external CSS classes and lack flexbox/grid. Quill implements alignment and indentation via `ql-align-*` / `ql-indent-*` classes, which such clients discard — so those formats are excluded from the toolbar and remaining styles are inlined at save time.
- **Existing patterns:** the admin panel loads Tailwind and FontAwesome from CDN, so a CDN-hosted editor is consistent. `nh3` and `markdown` are already dependencies (used for blog rendering); `nh3` is reused here for sanitization.
- **Nothing is in production yet**, but hand-written or pasted HTML templates must survive editing (hence the Source toggle).

## Architecture

```
messaging/
  placeholders.py    # registry + context building + placeholder discovery
  rendering.py       # (rewritten) render text/html against a context
  emailhtml.py       # sanitize + CSS-inline pipeline for stored body HTML
  api.py             # + placeholders list endpoint, + preview endpoint
brand/static/brand/js/admin/
  editor.js          # Quill setup, placeholder insert, source toggle, preview (shared)
```

**Migration required:** a `body_source` `TextField` is added to both `EmailTemplate` and `Campaign` (see §3).

## 1. Placeholder registry (`messaging/placeholders.py`)

A module-level registry is the **single source of truth** consumed by the renderer, the insert-menu UI, and the preview sample data. Each entry declares:

- `key` — the placeholder name (e.g. `first_name`)
- `label` — human label for the menu (e.g. "First name")
- `description` — one line explaining it
- `sample` — value used in preview rendering

Core placeholders:

| Key | Resolves to | Sample |
|---|---|---|
| `name` | `CampaignRecipient.name` (may be blank) | `Ada Lovelace` |
| `first_name` | First whitespace-separated token of `name` | `Ada` |
| `email` | `CampaignRecipient.email` | `ada@example.com` |
| `date` | Send date, formatted `%B %d, %Y` | `July 19, 2026` |
| `year` | Send year | `2026` |
| `unsubscribe_url` | Per-recipient signed unsubscribe URL | `https://…/unsubscribe/…/` |

Functions:

- `build_context(recipient, unsubscribe_url, now=None) -> dict[str, str]` — resolves the core set for one recipient. `now` is injectable so date-dependent tests are deterministic.
- `sample_context() -> dict[str, str]` — registry sample values, used by preview.
- `find_placeholders(text) -> list[str]` — all placeholder keys appearing in a string.
- `unknown_placeholders(text) -> list[str]` — those not in the registry, for the editor warning.

Pattern: `\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}` — tolerant of `{{name}}`, `{{ name }}`, `{{  name  }}`.

**Extensibility:** `build_context` accepts an optional `extra: dict` merged over the core set. Sub-project 2 will pass per-recipient CSV columns through it without changing the renderer.

## 2. Renderer (`messaging/rendering.py`, rewritten)

Replaces the current hardcoded functions with context-driven rendering:

- `render_text(template_str, context) -> str` — substitutes placeholders **without** escaping. Used for the subject and the plain-text alternative.
- `render_html(template_str, context) -> str` — substitutes placeholders with values **HTML-escaped** (`django.utils.html.escape`). Used for the HTML body.
- `html_to_text(html) -> str` — retained; additionally unescapes HTML entities so the text part reads correctly (today `&amp;` survives into plain text).

**Unknown-key policy:** a placeholder not present in the context resolves to the **empty string**. Rationale: a literal `{{ compnay }}` reaching a recipient is worse than a blank. The editor surfaces unknown keys before save (§5), so the typo is caught by a human rather than silently shipped.

Subject and body use the same context, eliminating today's asymmetry.

**Call-site update:** `process_email_outbox._send_one` switches to `build_context(...)` + `render_text`/`render_html`. Its existing behaviour (guaranteed unsubscribe footer, `List-Unsubscribe` headers, plain-text alternative) is unchanged.

## 3. Email HTML pipeline (`messaging/emailhtml.py`)

Two single-responsibility functions, and **both outputs are stored**:

- `sanitize_email_html(html) -> str` — `nh3` against an email-safe allowlist: permits structural/formatting tags (`p`, `br`, `strong`, `em`, `u`, `a`, `ul`, `ol`, `li`, `h1`–`h4`, `blockquote`, `hr`, `img`, `table`/`tr`/`td`/`th`, `span`, `div`) and the `style`, `href`, `src`, `alt`, `width`, `height` attributes. Strips `<script>`, event handlers, and other unsafe constructs.
- `inline_email_css(html) -> str` — wraps the sanitized fragment in a minimal document carrying a small `BASE_EMAIL_CSS` stylesheet (readable defaults for body text, headings, links, lists, blockquote), inlines it with `css-inline`, and returns the body fragment with the now-redundant `<style>` block removed.

### Why both are stored

`EmailTemplate` and `Campaign` each carry two fields:

| Field | Contents | Used for |
|---|---|---|
| `body_source` | Sanitized authored HTML, **not** inlined | Loading back into the editor; regenerating `body_html` |
| `body_html` | `inline_email_css(body_source)` | Sending (and campaign snapshots) |

Storing only the inlined result would mean re-opening a template shows markup bloated with `style` attributes that Quill then re-normalizes, and every save would re-inline already-inlined content. Keeping the source separate makes editing lossless and re-inlining deterministic — the round trip is `body_source → editor → body_source`, never through the inlined form.

It also removes the downside of inlining at save time: because the source is retained, `body_html` can be **regenerated** from `body_source` after a `BASE_EMAIL_CSS` change. (A management command to bulk-regenerate is enabled by this design but is **not** in scope here.)

Sanitize-before-inline, so the inliner only ever processes clean input. Inlining stays at **save**, not send, keeping the send path fast; campaigns continue to snapshot `body_html` at build time, so an in-flight campaign is unaffected by later template edits.

**Call site:** invoked in the DRF serializers — `EmailTemplateSerializer` and `CampaignSerializer` — so every write path (create, update, and a campaign seeded from a template) is covered by one rule and the models stay free of presentation logic. Clients submit `body_source`; the server derives `body_html`, which is **read-only** in the API. Seeding a campaign from a template copies `body_source` and re-derives `body_html`.

**Migration:** adds `body_source` (`TextField`, blank, default `""`) to `EmailTemplate` and `Campaign`, with a data migration backfilling `body_source = body_html` for existing rows (current stored values are un-inlined authored HTML, so they are valid sources).

**New dependency:** `css-inline` (Rust-backed, no lxml requirement), added to `brandtechsolution/requirements.txt`.

## 4. Editor (`brand/static/brand/js/admin/editor.js`)

Quill 2.x from CDN, initialized for both the Templates and Campaigns body fields by a shared helper so the two sections cannot diverge.

**Toolbar (email-safe only):** bold, italic, underline, link, ordered list, bullet list, heading (H2/H3), blockquote, clean. **Excluded:** text alignment and indentation — Quill implements these as CSS classes that email clients discard.

**Insert placeholder:** a custom toolbar dropdown populated at load from `GET /api/messaging/placeholders/`, inserting `{{ key }}` at the cursor. The subject `<input>` gets an equivalent insert control that splices at its caret position.

**Source toggle:** a "Source" button swaps the Quill surface for a raw `<textarea>` holding the current HTML.
- Quill → Source: textarea receives `quill.root.innerHTML`.
- Source → Quill: Quill is loaded from the textarea content; **the UI warns that returning to the visual editor may normalize markup Quill does not model.**
- Whichever view is active at submit time provides the saved value; in Source mode the raw text is submitted verbatim. Server-side sanitize + inline (§3) applies either way.

This protects HTML pasted from a designer or marketplace while keeping the visual editor as the default.

## 5. API endpoints (`messaging/api.py`)

Both staff-only (`IsAdminUser`), consistent with every other admin endpoint:

- **`GET /api/messaging/placeholders/`** → `[{key, label, description, sample}, …]` from the registry. Drives the insert menu.
- **`POST /api/messaging/preview/`** with `{subject, body_source}` → `{subject, body_html, unknown: [...]}`. The submitted source is run through the full save pipeline (`sanitize_email_html` → `inline_email_css`) and then the **same renderer used at send time** with `sample_context()`, so the preview reflects exactly what will be delivered rather than an approximation. Returns unknown placeholder keys for the typo warning.

The preview response is displayed in a **sandboxed `<iframe>`** so the admin panel's Tailwind styles cannot leak in and flatter the result.

## 6. UI integration

`_templates.html` and `_campaigns.html` each gain: the Quill container plus hidden input for the body, the Source toggle, the insert-placeholder controls (body and subject), a "Preview" button, the preview iframe, and an inline warning area listing unknown placeholders.

Editing loads **`body_source`** into the editor (never the inlined `body_html`), and submits `body_source`. `applyTemplate()` in `campaigns.js` copies the template's `body_source` into the campaign form, letting the server re-derive the campaign's `body_html`. Existing dark-theme Tailwind language (`bg-dark-card`, `border-dark-border`, `brand-blue`) is preserved; Quill's default theme is overridden to match.

Untrusted values rendered into these views continue to pass through the existing `escapeHtml` helper — the stored-XSS fix must not regress.

## 7. Testing

- **Placeholders:** spacing variants resolve; `first_name` derives from `name` and is blank when `name` is blank; `date`/`year` deterministic via injected `now`; `unknown_placeholders` reports typos and ignores valid keys.
- **Rendering:** unknown key renders empty; `render_html` escapes `&`, `<`, `>` in values while `render_text` does not; subject and body resolve the same keys; `html_to_text` unescapes entities.
- **Email HTML:** sanitizer strips `<script>` and `onerror=` while preserving `<a href>`, `<img src>`, and `style`; `inline_email_css` converts a stylesheet rule into an inline `style` attribute.
- **Source/derived split:** saving stores sanitized-but-not-inlined HTML in `body_source` and inlined HTML in `body_html`; `body_html` is read-only via the API and always equals `inline_email_css(body_source)`; an edit round trip (`save → reload → save`) leaves `body_source` byte-identical, proving no compounding inline styles; seeding a campaign from a template copies the source and re-derives the inlined body; the data migration backfills `body_source` from existing `body_html`.
- **Endpoints:** both are staff-only (anonymous → 401/403); preview returns rendered output plus the unknown list.
- **Regression:** the existing 67 messaging tests pass against the rewritten renderer, including the send-engine suite.

## Deferred (sub-project 2, separate spec)

- Per-recipient `extra_fields` and CSV/XLSX column → placeholder mapping (`{{ company }}`).
- Email validation: syntax (Django validator) plus MX/domain lookup.
- Campaign recipient list: view (paginated, searchable), remove individuals, add manually, per-recipient validity flag.

## Deferred (broader backlog, unchanged)

Events management, Appointments management, Dashboard analytics, saved audience lists.
