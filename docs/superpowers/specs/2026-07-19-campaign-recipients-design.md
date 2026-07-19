# Campaign Recipient Management + Email Validation — Design

**Date:** 2026-07-19
**Status:** Approved (design), pending implementation plan
**Scope:** Part of sub-project 2. Covers viewing, removing and adding individual campaign recipients, plus email validation. Per-recipient custom fields from CSV/XLSX column mapping (enabling placeholders like `{{ company }}`) remains deferred to its own spec.

## Summary

Today an admin can select audience *sources* and see a resolved count, but cannot see which addresses were resolved or exclude any of them. `CampaignRecipient` rows exist in the database, but nothing exposes them — there is no serializer, no viewset and no route. This work adds a staff-only recipients API and a modal UI to inspect, search, remove and add recipients, plus syntax and MX-domain validation so dead addresses can be spotted before sending.

## Context & constraints

- **No recipient API exists.** `messaging/api_urls.py` registers only `inquiries`, `templates` and `campaigns`, plus the `extract-emails`, `placeholders` and `preview` function views.
- **`build_recipients(campaign, source_keys, manual_emails)`** (`messaging/audience.py`) already merges sources, lowercases and de-duplicates by email, filters against `Suppression`, bulk-creates rows with `ignore_conflicts=True`, and sets `campaign.total`. New code must reuse these rules rather than reimplement them.
- **`CampaignRecipient`** currently carries `campaign`, `email`, `name`, `status` (`pending`/`sending`/`sent`/`failed`/`skipped`), `attempts`, `error`, `sent_at`, `claim_token`, `claimed_at`, with `unique_together = ("campaign", "email")`.
- **Campaign statuses:** `draft`/`queued`/`sending`/`sent`/`paused`/`failed`. The outbox sender claims rows by token and only ever sends rows in `pending`.
- **DRF has no global permission or pagination default in this project.** Every admin endpoint sets `permission_classes = [IsAdminUser]` explicitly; an unbounded list endpoint would return every row, so pagination must be declared explicitly too.
- **The admin panel had a stored-XSS bug** (public contact-form text rendered raw into `innerHTML`). Every value rendered into the panel goes through the shared `escapeHtml()` helper in `core.js`. That must not regress — recipient emails and names are partly attacker-supplied via the public contact form.

## 1. Data model

`CampaignRecipient` gains two fields:

| Field | Type | Purpose |
|---|---|---|
| `validation_status` | `CharField(max_length=20, default="unknown")` | `unknown` / `valid` / `invalid_syntax` / `invalid_domain` |
| `validated_at` | `DateTimeField(null=True, blank=True)` | When the MX check last ran for this row |

One migration; existing rows default to `unknown`.

## 2. Validation, split by cost

DNS lookups are slow and can hang. `build_recipients` is a synchronous API call, so a list spanning many unique domains could stall the request for a minute or more. Validation is therefore split:

- **Syntax validation runs during `build_recipients`.** Django's `validate_email` — instant, no network. Rows are written with `validation_status` of `valid` (syntactically fine, domain unchecked) or `invalid_syntax`.
- **MX/domain checking runs as an explicit action** (`POST /recipients/validate/`), triggered by a "Check domains" button in the modal — never implicitly on Build.

`messaging/validation.py` provides:

- `validate_syntax(email) -> bool` — wraps Django's `validate_email`.
- `domain_has_mx(domain) -> bool` — DNS MX lookup with a short timeout, returning `False` on `NXDOMAIN`/no-answer and on timeout.
- `validate_campaign_recipients(campaign) -> dict` — runs the MX pass over that campaign's rows, updates `validation_status`/`validated_at`, and returns counts per status.

**Domain results are cached** via Django's cache framework keyed on the domain (recipients heavily share domains such as `gmail.com`), so a large list costs one lookup per *unique* domain rather than one per address. Timeouts resolve to `invalid_domain` rather than raising.

**New dependency:** `dnspython`.

### Invalid addresses are flagged, not auto-skipped

The sender's behaviour is unchanged: a row marked `invalid_domain` is still `pending` and will still be attempted. Flagged rows are made obvious in the UI and removable in one click via **Remove all invalid**. Silently dropping recipients the admin never chose to drop would be the wrong default; the admin stays in control.

## 3. Recipients API

A new `CampaignRecipientViewSet` registered at `/api/messaging/recipients/`, `permission_classes = [IsAdminUser]`, with **explicit pagination** (`PageNumberPagination`, page size 50) declared on the viewset because the project sets no global default.

| Endpoint | Behaviour |
|---|---|
| `GET /recipients/?campaign=<id>&search=<text>&page=<n>` | Paginated list scoped to one campaign. `search` matches email or name (case-insensitive substring). `campaign` is required — an unscoped list is rejected with 400 rather than returning every recipient of every campaign. |
| `POST /recipients/` `{campaign, email, name}` | Adds one address. Lowercases and strips it, rejects duplicates within the campaign (400), rejects suppressed addresses (400), and applies syntax validation. Increments `campaign.total`. Allowed while the campaign is `draft`, `queued`, `sending` or `paused` — a new `pending` row is simply picked up by the next outbox run. Rejected with 400 for `sent`/`failed`, which are finished. |
| `DELETE /recipients/<id>/` | See removal semantics below. |
| `POST /recipients/validate/` `{campaign}` | Runs the MX pass; returns counts per `validation_status`. |
| `POST /recipients/remove_invalid/` `{campaign}` | Bulk-removes rows whose `validation_status` is `invalid_syntax` or `invalid_domain`, using the same removal semantics. Returns the number removed. |

### Removal semantics

Removal behaviour depends on the campaign's status, so that a recipient can be pulled out mid-send without corrupting counters or losing history:

- **Campaign is `draft`** — the row is **deleted** and `campaign.total` is decremented. The audience is still being composed, so nothing of value is lost.
- **Campaign is `queued`, `sending` or `paused`** — the row is **marked `skipped`** and `total` is left alone. The address will not be emailed (the sender only claims `pending` rows), and the send record stays coherent.
- **Campaign is `sent` or `failed`** — removal is rejected with 400. The campaign is finished; its history is immutable.

A row already in `sent`, `sending` or `failed` is never deleted or re-marked, since the message has been dispatched or is in flight.

## 4. UI — recipients modal

The campaign card gains a **"View recipients (N)"** button opening a full-width modal overlay. The existing audience column is already cramped; a modal keeps the card layout intact and gives the list room.

The modal contains:
- A search box filtering by email or name.
- The paginated list: email, name, send status badge, validity badge, and a remove button per row.
- An **add address** field (email + optional name).
- **Check domains** — runs the MX pass and refreshes the list.
- **Remove all invalid** — bulk removal, with a confirmation.
- Pagination controls.

Styling follows the existing dark-theme Tailwind language (`bg-dark-card`, `border-dark-border`, `brand-blue`/`brand-green` accents). **Every rendered value passes through `escapeHtml()`** — recipient names and emails originate partly from the public contact form and are therefore untrusted.

## 5. Files

| File | Responsibility |
|---|---|
| `messaging/validation.py` (new) | Syntax + MX validation, domain caching |
| `messaging/models.py` (modify) | Two fields on `CampaignRecipient` |
| `messaging/audience.py` (modify) | Set `validation_status` from syntax during build |
| `messaging/serializers.py` (modify) | `CampaignRecipientSerializer` |
| `messaging/api.py` (modify) | `CampaignRecipientViewSet` + `validate` / `remove_invalid` actions |
| `messaging/api_urls.py` (modify) | Register the `recipients` route |
| `brand/static/brand/js/admin/recipients.js` (new) | Modal: list, search, pagination, add, remove, validate |
| `brand/templates/brand/admin/_campaigns.html` (modify) | Modal markup + "View recipients" button |

Keeping the modal in its own JS module (rather than growing `campaigns.js`) matches the existing per-section split and keeps each file focused.

## 6. Testing

- **Removal semantics:** deleting from a `draft` campaign removes the row and decrements `total`; removing from `queued`/`sending`/`paused` marks `skipped` and leaves `total` unchanged; removal from `sent`/`failed` returns 400; a `sent` row is never deleted.
- **Add:** succeeds with normalisation (lowercase/strip) and increments `total`; duplicate within the campaign → 400; suppressed address → 400; syntactically invalid address is stored flagged; adding to a `sending` campaign succeeds and the row is `pending`; adding to a `sent` campaign → 400.
- **List:** requires `campaign` (unscoped → 400); paginates; `search` matches email and name; rows of other campaigns never leak in.
- **Validation:** `validate_syntax` accepts/rejects correctly; `domain_has_mx` is exercised with a **stubbed resolver** — no real DNS in tests — covering a domain with MX, `NXDOMAIN`, and a timeout (which must resolve to `invalid_domain`, not raise); the domain cache means N addresses on one domain trigger one lookup.
- **`remove_invalid`:** removes only flagged rows and honours the draft/sending rule.
- **Permissions:** every endpoint returns 401/403 for anonymous.
- **Regression:** the existing 104 messaging tests stay green, including the send-engine suite (the sender's behaviour is deliberately unchanged).

## Deferred

- Per-recipient `extra_fields` and CSV/XLSX column → placeholder mapping (`{{ company }}`).
- Auto-skipping invalid addresses at send time (currently flagged only, by explicit decision).
- Saved/reusable audience lists.
- Events management, Appointments management, Dashboard analytics.
