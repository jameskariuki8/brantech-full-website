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

No migration: `body_html` remains a `TextField`.

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

`prepare_email_html(html) -> str`, applied when a template or campaign body is saved:

1. **Sanitize** with `nh3` against an email-safe allowlist — permits structural/formatting tags (`p`, `br`, `strong`, `em`, `u`, `a`, `ul`, `ol`, `li`, `h1`–`h4`, `blockquote`, `hr`, `img`, `table`/`tr`/`td`/`th`, `span`, `div`) and the `style`, `href`, `src`, `alt`, `width`, `height` attributes. Strips `<script>`, event handlers, and other unsafe constructs.
2. **Inline CSS** using `css-inline`: the sanitized fragment is wrapped in a minimal document carrying a small `BASE_EMAIL_CSS` stylesheet (readable defaults for body text, headings, links, lists, blockquote), inlined, then the body fragment is returned with the now-redundant `<style>` block removed.

Sanitize-before-inline so the inliner only ever processes clean input.

Applied at **save**, not send: the send path stays fast, and campaigns already snapshot `body_html` at build time. Consequence to accept: changing `BASE_EMAIL_CSS` later does not retroactively restyle existing templates.

**Call site:** invoked in the DRF serializers — `EmailTemplateSerializer.validate_body_html` and `CampaignSerializer.validate_body_html` — so every write path (create, update, and a campaign seeded from a template) is covered by one rule, and the models stay free of presentation logic. Because the function is idempotent, re-saving an already-prepared body is safe.

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
- **`POST /api/messaging/preview/`** with `{subject, body_html}` → `{subject, body_html, unknown: [...]}`. Renders through the **same renderer used at send time** with `sample_context()`, so the preview is faithful rather than an approximation, and returns unknown placeholder keys for the typo warning.

The preview response is displayed in a **sandboxed `<iframe>`** so the admin panel's Tailwind styles cannot leak in and flatter the result.

## 6. UI integration

`_templates.html` and `_campaigns.html` each gain: the Quill container plus hidden input for the body, the Source toggle, the insert-placeholder controls (body and subject), a "Preview" button, the preview iframe, and an inline warning area listing unknown placeholders. Existing dark-theme Tailwind language (`bg-dark-card`, `border-dark-border`, `brand-blue`) is preserved; Quill's default theme is overridden to match.

Untrusted values rendered into these views continue to pass through the existing `escapeHtml` helper — the stored-XSS fix must not regress.

## 7. Testing

- **Placeholders:** spacing variants resolve; `first_name` derives from `name` and is blank when `name` is blank; `date`/`year` deterministic via injected `now`; `unknown_placeholders` reports typos and ignores valid keys.
- **Rendering:** unknown key renders empty; `render_html` escapes `&`, `<`, `>` in values while `render_text` does not; subject and body resolve the same keys; `html_to_text` unescapes entities.
- **Email HTML:** sanitizer strips `<script>` and `onerror=` while preserving `<a href>`, `<img src>`, and `style`; inlining converts a stylesheet rule into an inline `style` attribute; `prepare_email_html` is idempotent on already-inlined input.
- **Endpoints:** both are staff-only (anonymous → 401/403); preview returns rendered output plus the unknown list.
- **Regression:** the existing 67 messaging tests pass against the rewritten renderer, including the send-engine suite.

## Deferred (sub-project 2, separate spec)

- Per-recipient `extra_fields` and CSV/XLSX column → placeholder mapping (`{{ company }}`).
- Email validation: syntax (Django validator) plus MX/domain lookup.
- Campaign recipient list: view (paginated, searchable), remove individuals, add manually, per-recipient validity flag.

## Deferred (broader backlog, unchanged)

Events management, Appointments management, Dashboard analytics, saved audience lists.
