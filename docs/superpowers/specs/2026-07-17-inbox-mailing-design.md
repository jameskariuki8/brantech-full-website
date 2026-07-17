# Contact Inbox + Bulk Mailing — Design

**Date:** 2026-07-17
**Status:** Approved (design), pending implementation plan
**Scope:** One sub-project of a larger custom-admin-panel effort. Events management, Appointments management, and Dashboard analytics are explicitly deferred to their own later specs.

## Summary

Add a **contact inquiries inbox** and a **bulk email system** to the existing custom admin panel (`/admin-panel/`, staff-only). The public Contacts form currently POSTs to Formspree (external); inquiries never reach the database. This work replaces Formspree with a Django endpoint that persists submissions, surfaces them in an inbox, and lets an admin send throttled bulk HTML emails to a mix of recipient sources (inquiries, registered users, appointment clients, and manually pasted or document-imported addresses).

All new logic lives in a new Django app, **`messaging`**, matching the project's existing multi-app convention (`brand`, `appointments`, `ai_workflows`).

## Constraints & context

- **No background-task infrastructure.** The project is plain Django + gunicorn in Docker behind a Cloudflare tunnel. No Celery, Redis, RQ, or similar. Bulk sending must run outside the web request, so it uses a database-backed outbox processed by a management command on cron.
- **Email is Gmail SMTP** (`smtp.gmail.com`, `EMAIL_BACKEND = smtp`, `DEFAULT_FROM_EMAIL = EMAIL_HOST_USER`). Gmail throttles sends (~500/day free, ~2000/day Workspace). The design bounds volume via batch-size × cron cadence and ships conservative defaults.
- **Existing patterns to follow:** `brand/api.py` uses DRF `ModelViewSet`s registered on a `DefaultRouter`; the admin panel fetches JSON via `fetch()` with CSRF from cookie. New endpoints follow the same DRF style but are gated `IsAdminUser`.

## Architecture

```
messaging/                     # new app
  models.py                    # Inquiry, EmailTemplate, Campaign, CampaignRecipient, Suppression
  serializers.py               # DRF serializers
  api.py                       # DRF ViewSets + function endpoints (extract-emails, build-recipients)
  api_urls.py                  # router + custom routes, included at /api/messaging/
  views.py                     # public: contact submit, unsubscribe
  urls.py                      # public routes (contact submit, unsubscribe)
  imports.py                   # document email-extraction (csv/txt/xlsx/pdf/docx)
  audience.py                  # resolve recipient sources -> deduped, suppression-filtered rows
  management/commands/process_email_outbox.py
  tests/
```

Integration points:
- Project `urls.py`: `path('api/messaging/', include('messaging.api_urls'))` and `path('', include('messaging.urls'))` (for `/contacts/submit/` and `/unsubscribe/<token>/`).
- `INSTALLED_APPS += ['messaging']`.
- Admin panel (`brand/templates/brand/admin_panel.html`) gains a **Communications** sidebar group with **Inbox**, **Templates**, **Campaigns** sections that call `/api/messaging/` endpoints.

### Admin-panel extraction (targeted cleanup)

`admin_panel.html` is currently 585 lines of inline HTML + JS. Adding three sections inline would make it unmaintainable, especially with Events/Appointments/Analytics coming later. As part of this work:
- Extract per-section markup into template partials included from `admin_panel.html` (e.g. `brand/templates/brand/admin/_inbox.html`, `_templates.html`, `_campaigns.html`, and the existing blogs/projects sections).
- Move the inline `<script>` into static JS modules under `brand/static/brand/js/admin/` (e.g. `core.js`, `blogs.js`, `projects.js`, `inbox.js`, `templates.js`, `campaigns.js`).

Scope is limited to the admin panel. No unrelated refactoring of public pages or existing APIs.

## Data models (`messaging/models.py`)

### `Inquiry`
Contact-form submissions.
- `name` — CharField
- `email` — EmailField
- `phone` — CharField, blank
- `message` — TextField
- `status` — choices: `new` (default), `read`, `replied`, `archived`
- `created_at` — DateTimeField, auto_now_add
- `Meta.ordering = ['-created_at']`

### `EmailTemplate`
Reusable email content.
- `name` — CharField (internal label)
- `subject` — CharField
- `body_html` — TextField (admin-authored HTML)
- `created_at`, `updated_at`
- Supports placeholders `{{ name }}` and `{{ unsubscribe_url }}` rendered per recipient.

### `Campaign`
One bulk send.
- `name` — CharField (internal label)
- `subject` — CharField (snapshot; may originate from a template)
- `body_html` — TextField (snapshot at build time — editing a template later does not mutate a queued/sent campaign)
- `template` — FK to `EmailTemplate`, null/blank (provenance only)
- `status` — choices: `draft` (default), `queued`, `sending`, `sent`, `paused`, `failed`
- `total` — PositiveIntegerField, default 0
- `sent_count` — PositiveIntegerField, default 0
- `failed_count` — PositiveIntegerField, default 0
- `created_by` — FK to `auth.User`, null on delete SET_NULL
- `created_at`, `started_at` (null), `completed_at` (null)
- `Meta.ordering = ['-created_at']`

### `CampaignRecipient`
The outbox row and throttle unit. One per address per campaign.
- `campaign` — FK, related_name `recipients`, CASCADE
- `email` — EmailField
- `name` — CharField, blank (for `{{ name }}` personalization)
- `status` — choices: `pending` (default), `sent`, `failed`, `skipped`
- `attempts` — PositiveSmallIntegerField, default 0
- `error` — TextField, blank (last error message)
- `sent_at` — DateTimeField, null
- `Meta`: `unique_together = ('campaign', 'email')`, index on `(campaign, status)`

### `Suppression`
Unsubscribe / bounce list. Global across campaigns.
- `email` — EmailField, unique
- `reason` — choices: `unsubscribed`, `bounced`, `manual`
- `created_at`
- The sender skips (marks `skipped`) any recipient whose email is present here.

No persistent audience/contact-list model in v1 (YAGNI). Audiences are resolved into `CampaignRecipient` rows at build time.

## Contact-form migration (Formspree → Django)

- **New public view:** `POST /contacts/submit/` in `messaging/views.py`, routed by `messaging/urls.py`, named `contact_submit`.
  - Validate required fields (`name`, `email`, `message`); `phone` optional.
  - Honeypot: a hidden field that must stay empty; non-empty ⇒ silently accept-and-drop (return success without saving) to defeat naive bots. (Replaces the spam filtering Formspree provided.)
  - On success: create `Inquiry`, optionally send a notification email to `DEFAULT_FROM_EMAIL`, then redirect back to the contacts page with a Django `messages` success flash.
  - On validation error: redirect back with an error flash (preserve entered values is a nice-to-have, not required).
- **Template change (`brand/templates/brand/contacts.html`):**
  - Change `<form action="https://formspree.io/f/mpwvkpvk" method="POST">` to `action="{% url 'contact_submit' %}" method="POST"`.
  - Add `{% csrf_token %}`.
  - Add the hidden honeypot field.
  - Render `messages` flashes.

## Bulk send engine

### Outbox model
Sending is driven entirely by `CampaignRecipient` row state. A campaign in `queued` or `sending` has `pending` recipient rows waiting to be processed.

### Management command: `process_email_outbox`
Run by **cron every minute** (documented in README / entrypoint). Each invocation:
1. Select campaigns with status `queued` or `sending`. Transition `queued` → `sending` and set `started_at` on first processing.
2. For each such campaign, pull up to **`OUTBOX_BATCH_SIZE`** (default **50**) `pending` recipients (oldest first), guarding against concurrent runs via a status/lock check (`select_for_update` or a `sending` guard + skip if a run is already in progress).
3. For each recipient:
   - If email in `Suppression` ⇒ mark `skipped`, continue.
   - Render `subject`/`body_html` with `{{ name }}` and `{{ unsubscribe_url }}` (signed token) substituted.
   - Send via `EmailMultiAlternatives` (HTML alternative + a plain-text fallback derived from the HTML).
   - On success ⇒ `status='sent'`, `sent_at=now`, increment `campaign.sent_count`.
   - On failure ⇒ increment `attempts`, store `error`; if `attempts >= MAX_ATTEMPTS` (default **3**) ⇒ `status='failed'`, increment `campaign.failed_count`; else leave `pending` for a later run.
4. When a campaign has no remaining `pending` rows ⇒ set `status='sent'` (or `failed` if all failed) and `completed_at=now`.

### Throttling for Gmail
- Volume ceiling = `OUTBOX_BATCH_SIZE` × runs-per-hour. Default 50/run × 60 runs/hr = 3000/hr **maximum**; real cadence is bounded by how many pending rows exist.
- Ship conservative, env-configurable settings (`OUTBOX_BATCH_SIZE`, `OUTBOX_MAX_ATTEMPTS`, optional per-send delay). Document Gmail's ~500/day (free) and ~2000/day (Workspace) limits so the operator tunes batch size down to stay under them (e.g. batch 20 with a less-frequent cron).
- Restart-safe (all state in DB) and idempotent (row-level status transitions; no double-send because a row leaves `pending` before/at send).

## Recipient sources + document import

### Audience resolution (`messaging/audience.py`)
An audience is any mix of:
- **Inquiry contacts** — emails from `Inquiry`.
- **Registered users** — emails from `auth.User` (non-empty email).
- **Appointment clients** — emails from `appointments.Appointment`.
- **Manual / imported list** — pasted addresses and/or addresses extracted from uploaded documents.

On "build recipients," all selected sources are merged, **lowercased + de-duplicated by email**, **suppression-filtered**, and materialized as `CampaignRecipient` rows. The UI shows the resolved count before the send is queued. `name` is populated where the source provides it (Inquiry.name, User full name, Appointment.full_name); manual/imported entries may be email-only.

### Document import (`messaging/imports.py`)
- **Endpoint:** `POST /api/messaging/extract-emails/` (staff-only), multipart file upload.
- **Supported types:** `.csv`, `.txt`, `.xlsx`, `.pdf`, `.docx`. Enforce a max file size and reject other types.
- **Extraction:** harvest addresses via a robust email regex over extracted text —
  - CSV/TXT: read text directly.
  - XLSX: `openpyxl`, iterate cell values.
  - PDF: `pypdf`, extract page text.
  - DOCX: `python-docx`, extract paragraph text.
- **Returns:** JSON `{ "emails": [...], "count": N }` — deduplicated, Django-validated addresses — for the admin to review before inclusion. Extraction never sends; it only proposes addresses.
- **New dependencies:** `openpyxl`, `python-docx`, `pypdf` added to `requirements.txt`.

## Admin-panel UI (Communications group)

- **Inbox:** list inquiries with status badges (`new`/`read`/`replied`/`archived`); click to read full message; actions to mark read/replied/archived, delete, and **"Email this contact"** (seeds a campaign pre-addressed to that inquiry).
- **Templates:** CRUD list mirroring the Blogs/Projects visual language (create/edit/delete `EmailTemplate`).
- **Campaigns:** a compose → audience → review → send flow:
  1. **Compose** — subject + HTML body, or pick a template (snapshotted into the campaign).
  2. **Audience** — checkboxes for the four sources; paste box; document upload (calls extract-emails).
  3. **Review** — shows resolved, deduped, suppression-filtered recipient count.
  4. **Send** — queues the campaign (`status='queued'`); the cron command takes over.
  - Campaign list shows live `status` + `sent/total` progress and pause/resume (`sending` ⇄ `paused`).

## Compliance & security

- **Unsubscribe:** every email body includes `{{ unsubscribe_url }}` → public `GET /unsubscribe/<token>/` where `token` is a Django-signed email. The view adds the email to `Suppression` (reason `unsubscribed`, idempotent) and renders a confirmation page. No auth required.
- **Permissions:** all `/api/messaging/` admin endpoints require `IsAdminUser`. Public endpoints: `/contacts/submit/` and `/unsubscribe/<token>/`.
- **Uploads:** size- and type-guarded; parsing is defensive (never executes file content).
- **Email HTML** is admin-authored and treated as trusted; no sanitization of template bodies (only staff can create them).

## Testing (TDD)

- **Contact submit:** valid submission creates an `Inquiry` and flashes success; honeypot-filled submission is dropped without creating a row; missing required fields error out.
- **Audience resolution:** merging multiple sources de-duplicates by email; suppression-listed addresses are excluded; names populate from their source.
- **Document import:** each of csv/txt/xlsx/pdf/docx yields the expected deduped, validated address set; oversized/unknown types are rejected.
- **Send command:** respects `OUTBOX_BATCH_SIZE`; transitions `pending`→`sent` on success and `pending`→`failed` after `MAX_ATTEMPTS`; skips suppressed recipients; increments campaign counters; flips campaign to `sent`/`failed`/sets `completed_at` when drained; safe across overlapping runs.
- **Unsubscribe:** valid token adds a `Suppression` and is idempotent on repeat; tampered/invalid token is rejected.

## Deferred (future specs, not built here)

- Events management (CRUD section for the existing `Event` model).
- Appointments management (in-panel list + status updates).
- Dashboard analytics (richer stats/charts).
- Saved/reusable audience lists (v1 resolves audiences per-campaign only).
- Bounce handling beyond manual suppression (no inbound/webhook parsing in v1).
