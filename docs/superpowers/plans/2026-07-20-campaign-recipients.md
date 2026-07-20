# Campaign Recipient Management + Email Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin see, search, add and remove the individual email addresses attached to a campaign, and flag addresses that are syntactically malformed or whose domain has no MX record.

**Architecture:** A new `messaging/validation.py` holds pure validation logic (syntax via Django's validator, MX via `dnspython` with a per-domain cache). Two new fields on `CampaignRecipient` persist the verdict. A staff-only, explicitly-paginated `CampaignRecipientViewSet` exposes list/add/remove plus two collection actions (`validate`, `remove_invalid`). A modal overlay driven by a new `recipients.js` provides the UI. The send engine is deliberately untouched — invalid rows are flagged, never auto-skipped.

**Tech Stack:** Django 5.2.7, Django REST Framework, PostgreSQL, `dnspython` (new), vanilla JS + Tailwind (CDN) in the admin panel.

## Global Constraints

- **Working directory for all commands:** `/home/bigaddict/Projects/Codebases/brantech-full-website/brandtechsolution`. Use absolute paths; do not `cd` into subdirectories.
- **Every admin endpoint MUST set `permission_classes = [IsAdminUser]` explicitly.** This project defines no `DEFAULT_PERMISSION_CLASSES`; omitting it makes the endpoint public.
- **Every list endpoint MUST declare `pagination_class` explicitly.** This project defines no `DEFAULT_PAGINATION_CLASS`; omitting it returns every row.
- **Every value rendered into the admin panel MUST pass through the shared `escapeHtml()` helper** from `core.js`. Recipient names and emails originate partly from the public contact form and are untrusted. A stored-XSS bug of exactly this kind was fixed previously and must not regress.
- **Recipient emails are stored lowercased and stripped.** `audience.resolve_recipients()` already does this; every new write path must match.
- **The outbox sender (`messaging/management/commands/process_email_outbox.py`) is NOT modified by this plan.** A row flagged `invalid_domain` stays `pending` and is still attempted. This is an explicit product decision.
- **Test command:** `python manage.py test <label> --keepdb`. The `--keepdb` flag is required — without it the runner prompts interactively and the run aborts.
- **Validation status values:** exactly `unknown`, `valid`, `invalid_syntax`, `invalid_domain`.
- **Campaign statuses:** `draft`, `queued`, `sending`, `sent`, `paused`, `failed`.
- **Recipient statuses:** `pending`, `sending`, `sent`, `failed`, `skipped`.

## File Structure

| File | Responsibility |
|---|---|
| `messaging/validation.py` (create) | `validate_syntax`, `domain_has_mx` (cached), `validate_campaign_recipients` |
| `messaging/models.py` (modify) | `validation_status` + `validated_at` on `CampaignRecipient` |
| `messaging/migrations/0009_*.py` (generated) | The two new fields |
| `messaging/audience.py` (modify) | Stamp syntax verdict during `build_recipients` |
| `messaging/serializers.py` (modify) | `CampaignRecipientSerializer` |
| `messaging/api.py` (modify) | `CampaignRecipientViewSet`, `_remove_recipient` helper |
| `messaging/api_urls.py` (modify) | Register the `recipients` route |
| `brand/static/brand/js/admin/recipients.js` (create) | Modal: list, search, paginate, add, remove, validate |
| `brand/templates/brand/admin/_campaigns.html` (modify) | Modal markup + "View recipients" button target |
| `brand/static/brand/js/admin/campaigns.js` (modify) | "View recipients (N)" button on every campaign card |
| `brand/templates/brand/admin_panel.html` (modify) | `<script>` tag for `recipients.js` |
| `messaging/tests/test_validation.py` (create) | Tasks 1 & 3 |
| `messaging/tests/test_recipient_api.py` (create) | Tasks 4, 5, 6 |
| `messaging/tests/test_audience.py` (modify) | Task 2 |
| `messaging/tests/test_admin_panel_render.py` (modify) | Task 7 |
| `requirements.txt` (modify) | `dnspython` |
| `README.md` (modify) | Recipient management + validation docs |

---

### Task 1: Validation primitives (`validate_syntax`, `domain_has_mx`)

Pure functions with no database involvement. `domain_has_mx` performs a DNS lookup, so it is written from the start behind a single seam (`_query_mx`) that tests replace — **no test in this repo may ever perform a real DNS query.**

**Files:**
- Create: `messaging/validation.py`
- Create: `messaging/tests/test_validation.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `validate_syntax(email: str) -> bool`
  - `domain_has_mx(domain: str) -> bool`
  - `_query_mx(domain: str) -> object` — the DNS seam; tests patch `messaging.validation._query_mx`.
  - Constants `MX_TIMEOUT_SECONDS = 5`, `MX_CACHE_SECONDS = 3600`.

- [ ] **Step 1: Install the dependency and record it**

Run:

```bash
python -m pip install dnspython
```

Expected: `Successfully installed dnspython-2.x.x` (or `Requirement already satisfied`).

Then append `dnspython` to `requirements.txt`. The file is a flat, unpinned, unsorted list; add the new line at the end:

```
openpyxl
python-docx
pypdf
dnspython
```

- [ ] **Step 2: Write the failing tests**

Create `messaging/tests/test_validation.py`:

```python
from unittest.mock import patch

import dns.resolver
from django.core.cache import cache
from django.test import TestCase

from messaging.validation import domain_has_mx, validate_syntax


class ValidateSyntaxTests(TestCase):
    def test_accepts_ordinary_address(self):
        self.assertTrue(validate_syntax("ada@example.com"))

    def test_rejects_address_without_at_sign(self):
        self.assertFalse(validate_syntax("ada-at-example.com"))

    def test_rejects_address_without_domain(self):
        self.assertFalse(validate_syntax("ada@"))

    def test_rejects_blank(self):
        self.assertFalse(validate_syntax(""))

    def test_rejects_none(self):
        self.assertFalse(validate_syntax(None))


class DomainHasMxTests(TestCase):
    def setUp(self):
        # LocMemCache persists for the life of the process, so a verdict cached
        # by one test would leak into the next and mask a real lookup.
        cache.clear()

    def test_domain_with_mx_records_is_valid(self):
        with patch("messaging.validation._query_mx", return_value=["mx1.example.com"]):
            self.assertTrue(domain_has_mx("example.com"))

    def test_nxdomain_is_invalid(self):
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NXDOMAIN):
            self.assertFalse(domain_has_mx("nope.invalid"))

    def test_no_answer_is_invalid(self):
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NoAnswer):
            self.assertFalse(domain_has_mx("no-mx.example.com"))

    def test_timeout_is_invalid_and_does_not_raise(self):
        with patch("messaging.validation._query_mx", side_effect=dns.exception.Timeout):
            self.assertFalse(domain_has_mx("slow.example.com"))

    def test_empty_answer_is_invalid(self):
        with patch("messaging.validation._query_mx", return_value=[]):
            self.assertFalse(domain_has_mx("empty.example.com"))

    def test_result_is_cached_so_repeat_lookups_hit_dns_once(self):
        with patch("messaging.validation._query_mx", return_value=["mx1"]) as q:
            domain_has_mx("example.com")
            domain_has_mx("example.com")
            domain_has_mx("EXAMPLE.COM")
        self.assertEqual(q.call_count, 1)

    def test_negative_result_is_cached_too(self):
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NXDOMAIN) as q:
            self.assertFalse(domain_has_mx("nope.invalid"))
            self.assertFalse(domain_has_mx("nope.invalid"))
        self.assertEqual(q.call_count, 1)

    def test_blank_domain_is_invalid_without_a_lookup(self):
        with patch("messaging.validation._query_mx") as q:
            self.assertFalse(domain_has_mx(""))
        q.assert_not_called()
```

Note `import dns.exception` is reached via `import dns.resolver` (the `dns.resolver` module imports `dns.exception`), so both names resolve. If the test run reports `AttributeError: module 'dns' has no attribute 'exception'`, add an explicit `import dns.exception` at the top.

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
python manage.py test messaging.tests.test_validation --keepdb -v 2
```

Expected: FAIL — `ModuleNotFoundError: No module named 'messaging.validation'`.

- [ ] **Step 4: Write the implementation**

Create `messaging/validation.py`:

```python
"""Email address validation: cheap syntax checks and cached MX lookups.

Syntax validation is instant and runs wherever recipients are created. MX
lookups touch the network and are therefore never run implicitly -- they are
driven by an explicit admin action (see validate_campaign_recipients).
"""

import logging

import dns.exception
import dns.resolver
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

logger = logging.getLogger(__name__)

MX_TIMEOUT_SECONDS = 5
MX_CACHE_SECONDS = 3600


def validate_syntax(email):
    """True if `email` is a syntactically well-formed address. Never raises."""
    if not email:
        return False
    try:
        validate_email(email)
    except ValidationError:
        return False
    return True


def _query_mx(domain):
    """Resolve MX records for `domain`. The single DNS seam -- tests patch this."""
    resolver = dns.resolver.Resolver()
    resolver.timeout = MX_TIMEOUT_SECONDS
    resolver.lifetime = MX_TIMEOUT_SECONDS
    return resolver.resolve(domain, "MX")


def domain_has_mx(domain):
    """True if `domain` publishes at least one MX record.

    Results (positive and negative alike) are cached per domain: a recipient
    list of 500 addresses is typically a handful of distinct domains, and
    without caching that would be 500 network round trips.

    Any DNS failure -- NXDOMAIN, no answer, dead nameserver, timeout -- is
    reported as False rather than raised. A caller triggered by an admin
    button must not 500 because a nameserver was slow.
    """
    domain = (domain or "").strip().lower()
    if not domain:
        return False

    key = f"messaging:mx:{domain}"
    cached = cache.get(key)
    # A cached False is a real verdict, so test for the miss sentinel itself
    # rather than for falseness.
    if cached is not None:
        return cached

    try:
        answers = _query_mx(domain)
        result = bool(answers)
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.exception.Timeout,
    ):
        result = False
    except Exception as exc:  # noqa: BLE001 - a lookup failure is not an outage
        logger.warning("MX lookup failed for %s: %s", domain, exc)
        result = False

    cache.set(key, result, MX_CACHE_SECONDS)
    return result
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
python manage.py test messaging.tests.test_validation --keepdb -v 2
```

Expected: PASS — `Ran 14 tests ... OK`.

- [ ] **Step 6: Commit**

```bash
git add messaging/validation.py messaging/tests/test_validation.py requirements.txt
git commit -m "feat(messaging): email syntax and cached MX-domain validation"
```

---

### Task 2: Persist the verdict — model fields + syntax stamping at build

**Files:**
- Modify: `messaging/models.py` (`CampaignRecipient`, after line 111 `status`)
- Create: `messaging/migrations/0009_*.py` (generated by `makemigrations`)
- Modify: `messaging/audience.py:53-66` (`build_recipients`)
- Modify: `messaging/tests/test_audience.py`

**Interfaces:**
- Consumes: `validate_syntax` from Task 1.
- Produces: `CampaignRecipient.validation_status` (str, default `"unknown"`) and `CampaignRecipient.validated_at` (datetime or `None`).

- [ ] **Step 1: Write the failing tests**

Append to `messaging/tests/test_audience.py`:

```python
class BuildRecipientsValidationTests(TestCase):
    def _campaign(self):
        return Campaign.objects.create(
            name="C", subject="S", body_source="<p>x</p>", body_html="<p>x</p>"
        )

    def test_well_formed_address_is_marked_valid(self):
        campaign = self._campaign()
        build_recipients(campaign, [], ["ada@example.com"])
        row = CampaignRecipient.objects.get(campaign=campaign, email="ada@example.com")
        self.assertEqual(row.validation_status, "valid")

    def test_malformed_address_is_marked_invalid_syntax(self):
        campaign = self._campaign()
        build_recipients(campaign, [], ["not-an-email"])
        row = CampaignRecipient.objects.get(campaign=campaign, email="not-an-email")
        self.assertEqual(row.validation_status, "invalid_syntax")

    def test_build_does_not_stamp_validated_at(self):
        # Syntax is checked at build; the MX pass is a separate, explicit action.
        campaign = self._campaign()
        build_recipients(campaign, [], ["ada@example.com"])
        row = CampaignRecipient.objects.get(campaign=campaign, email="ada@example.com")
        self.assertIsNone(row.validated_at)
```

Check the existing imports at the top of `test_audience.py` — add whatever of `Campaign`, `CampaignRecipient`, `build_recipients`, `TestCase` is not already imported. Do not duplicate an existing import line.

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python manage.py test messaging.tests.test_audience --keepdb -v 2
```

Expected: FAIL — `AttributeError: 'CampaignRecipient' object has no attribute 'validation_status'`.

- [ ] **Step 3: Add the model fields**

In `messaging/models.py`, inside `class CampaignRecipient`, immediately after the `status` field (line 111), insert:

```python
    VALIDATION_CHOICES = [
        ("unknown", "Not checked"),
        ("valid", "Valid"),
        ("invalid_syntax", "Malformed address"),
        ("invalid_domain", "Domain has no mail server"),
    ]
    validation_status = models.CharField(
        max_length=20, choices=VALIDATION_CHOICES, default="unknown"
    )
    # Set by the MX pass only. A row whose syntax was checked at build time
    # but whose domain has never been looked up leaves this null.
    validated_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 4: Generate and apply the migration**

Run:

```bash
python manage.py makemigrations messaging
```

Expected: `Migrations for 'messaging': messaging/migrations/0009_campaignrecipient_validation_status_and_more.py` listing two `AddField` operations. Record the exact generated filename — it is needed for the commit.

Run:

```bash
python manage.py migrate messaging
```

Expected: `Applying messaging.0009_...  OK`.

- [ ] **Step 5: Stamp the syntax verdict during build**

In `messaging/audience.py`, add to the import block at the top:

```python
from .validation import validate_syntax
```

Then replace the `bulk_create` call in `build_recipients` (lines 56-62) with:

```python
    CampaignRecipient.objects.bulk_create(
        [
            CampaignRecipient(
                campaign=campaign,
                email=r["email"],
                name=r["name"],
                validation_status=(
                    "valid" if validate_syntax(r["email"]) else "invalid_syntax"
                ),
            )
            for r in recipients
        ],
        ignore_conflicts=True,
    )
```

Nothing else in the function changes: the `count`/`campaign.total` write below it stays as-is.

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
python manage.py test messaging.tests.test_audience --keepdb -v 2
```

Expected: PASS, including the pre-existing audience tests.

- [ ] **Step 7: Commit**

```bash
git add messaging/models.py messaging/migrations/ messaging/audience.py messaging/tests/test_audience.py
git commit -m "feat(messaging): store per-recipient validation status, stamped at build"
```

---

### Task 3: The campaign-wide MX pass

**Files:**
- Modify: `messaging/validation.py`
- Modify: `messaging/tests/test_validation.py`

**Interfaces:**
- Consumes: `domain_has_mx` (Task 1); `CampaignRecipient.validation_status` / `validated_at` (Task 2).
- Produces: `validate_campaign_recipients(campaign) -> dict` returning **exactly** the keys `{"valid": int, "invalid_syntax": int, "invalid_domain": int, "unknown": int}` — counts across *all* of that campaign's recipients after the pass. Task 6's API action and Task 7's UI both depend on this shape.

- [ ] **Step 1: Write the failing tests**

Append to `messaging/tests/test_validation.py`:

```python
from messaging.models import Campaign, CampaignRecipient
from messaging.validation import validate_campaign_recipients


class ValidateCampaignRecipientsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.campaign = Campaign.objects.create(
            name="C", subject="S", body_source="<p>x</p>", body_html="<p>x</p>"
        )

    def _recipient(self, email, validation_status="valid"):
        return CampaignRecipient.objects.create(
            campaign=self.campaign, email=email, validation_status=validation_status
        )

    def test_live_domain_stays_valid_and_is_stamped(self):
        row = self._recipient("ada@example.com")
        with patch("messaging.validation._query_mx", return_value=["mx1"]):
            validate_campaign_recipients(self.campaign)
        row.refresh_from_db()
        self.assertEqual(row.validation_status, "valid")
        self.assertIsNotNone(row.validated_at)

    def test_dead_domain_becomes_invalid_domain(self):
        row = self._recipient("ada@nope.invalid")
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NXDOMAIN):
            validate_campaign_recipients(self.campaign)
        row.refresh_from_db()
        self.assertEqual(row.validation_status, "invalid_domain")

    def test_malformed_rows_are_skipped_not_looked_up(self):
        row = self._recipient("not-an-email", validation_status="invalid_syntax")
        with patch("messaging.validation._query_mx") as q:
            validate_campaign_recipients(self.campaign)
        q.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.validation_status, "invalid_syntax")

    def test_shared_domain_costs_one_lookup(self):
        for i in range(5):
            self._recipient(f"user{i}@example.com")
        with patch("messaging.validation._query_mx", return_value=["mx1"]) as q:
            validate_campaign_recipients(self.campaign)
        self.assertEqual(q.call_count, 1)

    def test_returns_counts_for_every_status(self):
        self._recipient("ada@example.com")
        self._recipient("bad", validation_status="invalid_syntax")
        with patch("messaging.validation._query_mx", return_value=["mx1"]):
            counts = validate_campaign_recipients(self.campaign)
        self.assertEqual(
            counts,
            {"valid": 1, "invalid_syntax": 1, "invalid_domain": 0, "unknown": 0},
        )

    def test_other_campaigns_are_untouched(self):
        other = Campaign.objects.create(
            name="Other", subject="S", body_source="<p>x</p>", body_html="<p>x</p>"
        )
        stranger = CampaignRecipient.objects.create(
            campaign=other, email="bob@nope.invalid", validation_status="valid"
        )
        self._recipient("ada@example.com")
        with patch("messaging.validation._query_mx", return_value=["mx1"]):
            validate_campaign_recipients(self.campaign)
        stranger.refresh_from_db()
        self.assertEqual(stranger.validation_status, "valid")
        self.assertIsNone(stranger.validated_at)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python manage.py test messaging.tests.test_validation --keepdb -v 2
```

Expected: FAIL — `ImportError: cannot import name 'validate_campaign_recipients'`.

- [ ] **Step 3: Write the implementation**

Append to `messaging/validation.py`:

```python
def validate_campaign_recipients(campaign):
    """Run the MX pass over one campaign's recipients and return status counts.

    Rows already flagged `invalid_syntax` are left alone -- there is no domain
    worth looking up in a malformed address. Everything else is re-checked and
    stamped, so re-running the pass refreshes a stale verdict.
    """
    from .models import CampaignRecipient

    now = timezone.now()
    rows = CampaignRecipient.objects.filter(campaign=campaign).exclude(
        validation_status="invalid_syntax"
    )

    for row in rows:
        domain = (row.email or "").rsplit("@", 1)[-1]
        row.validation_status = "valid" if domain_has_mx(domain) else "invalid_domain"
        row.validated_at = now
        row.save(update_fields=["validation_status", "validated_at"])

    counts = {"valid": 0, "invalid_syntax": 0, "invalid_domain": 0, "unknown": 0}
    for status in CampaignRecipient.objects.filter(campaign=campaign).values_list(
        "validation_status", flat=True
    ):
        if status in counts:
            counts[status] += 1
    return counts
```

Add to the imports at the top of `messaging/validation.py`:

```python
from django.utils import timezone
```

`CampaignRecipient` is imported inside the function rather than at module scope so that `messaging.models` can import from `messaging.validation` in future without a circular import.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
python manage.py test messaging.tests.test_validation --keepdb -v 2
```

Expected: PASS — all 20 tests.

- [ ] **Step 5: Commit**

```bash
git add messaging/validation.py messaging/tests/test_validation.py
git commit -m "feat(messaging): campaign-wide MX validation pass with per-domain caching"
```

---

### Task 4: Recipients API — list and add

**Files:**
- Modify: `messaging/serializers.py`
- Modify: `messaging/api.py`
- Modify: `messaging/api_urls.py`
- Create: `messaging/tests/test_recipient_api.py`

**Interfaces:**
- Consumes: `validate_syntax` (Task 1); the model fields (Task 2).
- Produces:
  - `CampaignRecipientSerializer` in `messaging/serializers.py`.
  - `CampaignRecipientViewSet` in `messaging/api.py`, routed at `/api/messaging/recipients/`.
  - Response shape for list: DRF `PageNumberPagination` — `{"count": int, "next": url|null, "previous": url|null, "results": [...]}`. Each result: `{id, campaign, email, name, status, validation_status, validated_at, sent_at}`. Task 7's JS depends on this shape.

- [ ] **Step 1: Write the failing tests**

Create `messaging/tests/test_recipient_api.py`:

```python
from django.contrib.auth.models import User
from django.test import TestCase

from messaging.models import Campaign, CampaignRecipient, Suppression


class RecipientApiTestBase(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.client.force_login(self.staff)
        self.campaign = self._campaign()

    def _campaign(self, name="Launch", status="draft", total=0):
        return Campaign.objects.create(
            name=name, subject="S", body_source="<p>x</p>", body_html="<p>x</p>",
            status=status, total=total,
        )

    def _recipient(self, campaign=None, email="ada@example.com", **kwargs):
        return CampaignRecipient.objects.create(
            campaign=campaign or self.campaign, email=email, **kwargs
        )


class RecipientListTests(RecipientApiTestBase):
    def test_list_requires_a_campaign(self):
        resp = self.client.get("/api/messaging/recipients/")
        self.assertEqual(resp.status_code, 400)

    def test_list_rejects_a_non_numeric_campaign(self):
        resp = self.client.get("/api/messaging/recipients/?campaign=abc")
        self.assertEqual(resp.status_code, 400)

    def test_list_returns_only_that_campaigns_recipients(self):
        self._recipient(email="mine@example.com")
        other = self._campaign(name="Other")
        self._recipient(campaign=other, email="theirs@example.com")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertEqual(resp.status_code, 200)
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["mine@example.com"])

    def test_list_is_paginated(self):
        for i in range(55):
            self._recipient(email=f"user{i}@example.com")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        body = resp.json()
        self.assertEqual(body["count"], 55)
        self.assertEqual(len(body["results"]), 50)
        self.assertIsNotNone(body["next"])

    def test_search_matches_email(self):
        self._recipient(email="ada@example.com")
        self._recipient(email="bob@other.com")
        resp = self.client.get(
            f"/api/messaging/recipients/?campaign={self.campaign.id}&search=ADA"
        )
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["ada@example.com"])

    def test_search_matches_name(self):
        self._recipient(email="a@x.com", name="Ada Lovelace")
        self._recipient(email="b@x.com", name="Bob")
        resp = self.client.get(
            f"/api/messaging/recipients/?campaign={self.campaign.id}&search=lovelace"
        )
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["a@x.com"])

    def test_response_exposes_validation_status(self):
        self._recipient(validation_status="invalid_domain")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertEqual(resp.json()["results"][0]["validation_status"], "invalid_domain")

    def test_anonymous_cannot_list(self):
        self.client.logout()
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertIn(resp.status_code, (401, 403))


class RecipientAddTests(RecipientApiTestBase):
    def _add(self, email, name="", campaign=None):
        return self.client.post(
            "/api/messaging/recipients/",
            data={
                "campaign": (campaign or self.campaign).id,
                "email": email,
                "name": name,
            },
            content_type="application/json",
        )

    def test_add_creates_a_pending_recipient(self):
        resp = self._add("ada@example.com", name="Ada")
        self.assertEqual(resp.status_code, 201)
        row = CampaignRecipient.objects.get(campaign=self.campaign)
        self.assertEqual(row.email, "ada@example.com")
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.validation_status, "valid")

    def test_add_normalises_case_and_whitespace(self):
        resp = self._add("  ADA@Example.COM  ")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            CampaignRecipient.objects.filter(
                campaign=self.campaign, email="ada@example.com"
            ).exists()
        )

    def test_add_increments_campaign_total(self):
        self._add("ada@example.com")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 1)

    def test_duplicate_within_campaign_is_rejected(self):
        self._add("ada@example.com")
        resp = self._add("ada@example.com")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(CampaignRecipient.objects.filter(campaign=self.campaign).count(), 1)

    def test_duplicate_check_is_case_insensitive(self):
        self._add("ada@example.com")
        resp = self._add("ADA@EXAMPLE.COM")
        self.assertEqual(resp.status_code, 400)

    def test_suppressed_address_is_rejected(self):
        Suppression.objects.create(email="ada@example.com")
        resp = self._add("ada@example.com")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CampaignRecipient.objects.filter(campaign=self.campaign).exists())

    def test_malformed_address_is_rejected(self):
        # An address Django's own EmailField rejects never reaches the database.
        resp = self._add("not-an-email")
        self.assertEqual(resp.status_code, 400)

    def test_add_to_sending_campaign_is_allowed(self):
        sending = self._campaign(name="InFlight", status="sending")
        resp = self._add("ada@example.com", campaign=sending)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(CampaignRecipient.objects.get(campaign=sending).status, "pending")

    def test_add_to_paused_campaign_is_allowed(self):
        paused = self._campaign(name="Paused", status="paused")
        resp = self._add("ada@example.com", campaign=paused)
        self.assertEqual(resp.status_code, 201)

    def test_add_to_sent_campaign_is_rejected(self):
        finished = self._campaign(name="Done", status="sent")
        resp = self._add("ada@example.com", campaign=finished)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CampaignRecipient.objects.filter(campaign=finished).exists())

    def test_add_to_failed_campaign_is_rejected(self):
        finished = self._campaign(name="Dead", status="failed")
        resp = self._add("ada@example.com", campaign=finished)
        self.assertEqual(resp.status_code, 400)

    def test_anonymous_cannot_add(self):
        self.client.logout()
        resp = self._add("ada@example.com")
        self.assertIn(resp.status_code, (401, 403))
        self.assertFalse(CampaignRecipient.objects.exists())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python manage.py test messaging.tests.test_recipient_api --keepdb -v 2
```

Expected: FAIL — every test 404s, because `/api/messaging/recipients/` is not routed.

- [ ] **Step 3: Add the serializer**

In `messaging/serializers.py`, change the model import line to include `CampaignRecipient` and `Suppression`:

```python
from .models import Campaign, CampaignRecipient, EmailTemplate, Inquiry, Suppression
```

Add at the end of the file:

```python
ADDABLE_CAMPAIGN_STATUSES = {"draft", "queued", "sending", "paused"}


class CampaignRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignRecipient
        fields = [
            "id", "campaign", "email", "name", "status",
            "validation_status", "validated_at", "sent_at",
        ]
        read_only_fields = [
            "id", "status", "validation_status", "validated_at", "sent_at",
        ]

    def validate_email(self, value):
        # Match how audience.resolve_recipients() stores addresses, so the
        # unique_together check and the send path see the same string.
        return (value or "").strip().lower()

    def validate(self, attrs):
        campaign = attrs.get("campaign")
        if campaign and campaign.status not in ADDABLE_CAMPAIGN_STATUSES:
            raise serializers.ValidationError(
                {"detail": f"Cannot add recipients to a {campaign.status} campaign."}
            )

        email = attrs.get("email")
        if email and Suppression.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                {"detail": f"{email} has unsubscribed or bounced and cannot be added."}
            )
        return attrs

    def create(self, validated_data):
        validated_data["validation_status"] = (
            "valid" if validate_syntax(validated_data["email"]) else "invalid_syntax"
        )
        return super().create(validated_data)
```

Add to the imports at the top of `messaging/serializers.py`:

```python
from .validation import validate_syntax
```

Duplicates are caught by the `UniqueTogetherValidator` DRF derives automatically from `CampaignRecipient.Meta.unique_together = ("campaign", "email")`. It runs after `validate_email()` has lowercased the input, so `ADA@EXAMPLE.COM` collides with a stored `ada@example.com` as required.

- [ ] **Step 4: Add the viewset**

In `messaging/api.py`, extend the existing imports at the top of the file:

```python
from django.db.models import F, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from . import audience
from .models import Campaign, CampaignRecipient, EmailTemplate, Inquiry
from .serializers import (
    CampaignRecipientSerializer,
    CampaignSerializer,
    EmailTemplateSerializer,
    InquirySerializer,
)
```

Add after the existing `CampaignViewSet` class (i.e. after line 76, before the `from rest_framework.decorators import api_view...` block):

```python
class RecipientPagination(PageNumberPagination):
    # Declared explicitly: this project sets no DEFAULT_PAGINATION_CLASS, so
    # without this the endpoint would return every recipient in one response.
    page_size = 50


class CampaignRecipientViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignRecipientSerializer
    permission_classes = [IsAdminUser]
    pagination_class = RecipientPagination

    def get_queryset(self):
        qs = CampaignRecipient.objects.select_related("campaign").order_by("id")

        # Scoping applies to `list` only. get_object() runs this same method for
        # detail routes, where no `campaign` query parameter is present -- making
        # it mandatory there would break DELETE.
        if self.action != "list":
            return qs

        campaign_id = self.request.query_params.get("campaign")
        if not campaign_id:
            raise ValidationError({"detail": "A campaign query parameter is required."})
        if not str(campaign_id).isdigit():
            raise ValidationError({"detail": "campaign must be a numeric id."})
        qs = qs.filter(campaign_id=campaign_id)

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(email__icontains=search) | Q(name__icontains=search))
        return qs

    def perform_create(self, serializer):
        recipient = serializer.save()
        Campaign.objects.filter(pk=recipient.campaign_id).update(total=F("total") + 1)
```

- [ ] **Step 5: Route it**

In `messaging/api_urls.py`, add a registration line after the `campaigns` one:

```python
router.register(r"recipients", api.CampaignRecipientViewSet, basename="recipients")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
python manage.py test messaging.tests.test_recipient_api --keepdb -v 2
```

Expected: PASS — 20 tests.

- [ ] **Step 7: Commit**

```bash
git add messaging/serializers.py messaging/api.py messaging/api_urls.py messaging/tests/test_recipient_api.py
git commit -m "feat(messaging): staff API to list and add campaign recipients"
```

---

### Task 5: Removing a recipient

Removal is not a plain delete. While a campaign is still a draft the row is discarded outright; once it is queued or in flight the row is marked `skipped` so the send record stays coherent; once the campaign has finished, removal is refused.

**Files:**
- Modify: `messaging/api.py`
- Modify: `messaging/tests/test_recipient_api.py`

**Interfaces:**
- Consumes: `CampaignRecipientViewSet` (Task 4).
- Produces: `_remove_recipient(recipient) -> str | None` in `messaging/api.py` — returns `None` on success, or a human-readable refusal reason. Task 6's `remove_invalid` action calls it.

- [ ] **Step 1: Write the failing tests**

Append to `messaging/tests/test_recipient_api.py`:

```python
class RecipientRemoveTests(RecipientApiTestBase):
    def _delete(self, recipient):
        return self.client.delete(f"/api/messaging/recipients/{recipient.id}/")

    def test_draft_removal_deletes_the_row(self):
        self.campaign.total = 1
        self.campaign.save(update_fields=["total"])
        row = self._recipient()
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_draft_removal_decrements_total(self):
        self.campaign.total = 3
        self.campaign.save(update_fields=["total"])
        row = self._recipient()
        self._delete(row)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 2)

    def test_total_never_goes_below_zero(self):
        # total is a PositiveIntegerField; an underflow would be a database error.
        row = self._recipient()
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 204)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 0)

    def test_queued_removal_marks_skipped_and_keeps_total(self):
        campaign = self._campaign(name="Q", status="queued", total=1)
        row = self._recipient(campaign=campaign)
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 204)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")
        campaign.refresh_from_db()
        self.assertEqual(campaign.total, 1)

    def test_sending_campaign_removal_marks_skipped(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign)
        self._delete(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")

    def test_paused_campaign_removal_marks_skipped(self):
        campaign = self._campaign(name="P", status="paused", total=1)
        row = self._recipient(campaign=campaign)
        self._delete(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")

    def test_already_sent_row_is_not_touched(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, status="sent")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        row.refresh_from_db()
        self.assertEqual(row.status, "sent")

    def test_in_flight_row_is_not_touched(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, status="sending")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        row.refresh_from_db()
        self.assertEqual(row.status, "sending")

    def test_failed_row_is_not_touched(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, status="failed")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        row.refresh_from_db()
        self.assertEqual(row.status, "failed")

    def test_removal_from_sent_campaign_is_rejected(self):
        campaign = self._campaign(name="Done", status="sent", total=1)
        row = self._recipient(campaign=campaign)
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_removal_from_failed_campaign_is_rejected(self):
        campaign = self._campaign(name="Dead", status="failed", total=1)
        row = self._recipient(campaign=campaign)
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_anonymous_cannot_remove(self):
        row = self._recipient()
        self.client.logout()
        resp = self._delete(row)
        self.assertIn(resp.status_code, (401, 403))
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python manage.py test messaging.tests.test_recipient_api.RecipientRemoveTests --keepdb -v 2
```

Expected: FAIL — the default `ModelViewSet.destroy` deletes unconditionally, so `test_queued_removal_marks_skipped_and_keeps_total` and the sent/failed-campaign tests fail (204 instead of 400, rows gone).

- [ ] **Step 3: Write the implementation**

In `messaging/api.py`, add above `class CampaignRecipientViewSet`:

```python
REMOVABLE_CAMPAIGN_STATUSES = {"draft", "queued", "sending", "paused"}
DISPATCHED_RECIPIENT_STATUSES = {"sending", "sent", "failed"}


def _remove_recipient(recipient):
    """Remove one recipient from its campaign. Returns None on success.

    Behaviour depends on how far the campaign has progressed:
      draft                    -> delete outright and give the slot back
      queued/sending/paused    -> mark skipped; the sender only claims
                                  `pending` rows, so it will never be emailed
      sent/failed              -> refuse; a finished campaign's record is history

    On failure, returns the reason as a string for the caller to surface.
    """
    campaign = recipient.campaign
    if campaign.status not in REMOVABLE_CAMPAIGN_STATUSES:
        return f"Cannot change recipients of a {campaign.status} campaign."

    if recipient.status in DISPATCHED_RECIPIENT_STATUSES:
        return f"This message is already {recipient.status} and cannot be withdrawn."

    if campaign.status == "draft":
        recipient.delete()
        # total is a PositiveIntegerField, so guard the decrement rather than
        # letting a stale counter underflow into a database error.
        Campaign.objects.filter(pk=campaign.pk, total__gt=0).update(
            total=F("total") - 1
        )
        return None

    recipient.status = "skipped"
    recipient.save(update_fields=["status"])
    return None
```

Then add this method to `CampaignRecipientViewSet`, after `perform_create`:

```python
    def destroy(self, request, *args, **kwargs):
        recipient = self.get_object()
        error = _remove_recipient(recipient)
        if error:
            return Response({"detail": error}, status=400)
        return Response(status=204)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
python manage.py test messaging.tests.test_recipient_api --keepdb -v 2
```

Expected: PASS — 32 tests.

- [ ] **Step 5: Commit**

```bash
git add messaging/api.py messaging/tests/test_recipient_api.py
git commit -m "feat(messaging): status-aware recipient removal"
```

---

### Task 6: The `validate` and `remove_invalid` actions

**Files:**
- Modify: `messaging/api.py`
- Modify: `messaging/tests/test_recipient_api.py`

**Interfaces:**
- Consumes: `validate_campaign_recipients` (Task 3), `_remove_recipient` (Task 5).
- Produces:
  - `POST /api/messaging/recipients/validate/` with body `{"campaign": <id>}` → `200 {"valid": n, "invalid_syntax": n, "invalid_domain": n, "unknown": n}`.
  - `POST /api/messaging/recipients/remove_invalid/` with body `{"campaign": <id>}` → `200 {"removed": n, "skipped": n}` where `skipped` counts flagged rows that could not be removed.

- [ ] **Step 1: Write the failing tests**

Append to `messaging/tests/test_recipient_api.py`. Add these imports at the top of the file (alongside the existing ones):

```python
from unittest.mock import patch

import dns.resolver
from django.core.cache import cache
```

Then:

```python
class RecipientValidateActionTests(RecipientApiTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def _validate(self, campaign=None):
        return self.client.post(
            "/api/messaging/recipients/validate/",
            data={"campaign": (campaign or self.campaign).id},
            content_type="application/json",
        )

    def test_validate_returns_counts(self):
        self._recipient(email="ada@example.com")
        with patch("messaging.validation._query_mx", return_value=["mx1"]):
            resp = self._validate()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {"valid": 1, "invalid_syntax": 0, "invalid_domain": 0, "unknown": 0},
        )

    def test_validate_flags_a_dead_domain(self):
        row = self._recipient(email="ada@nope.invalid")
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NXDOMAIN):
            self._validate()
        row.refresh_from_db()
        self.assertEqual(row.validation_status, "invalid_domain")

    def test_validate_requires_a_campaign(self):
        resp = self.client.post(
            "/api/messaging/recipients/validate/", data={}, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_validate_rejects_an_unknown_campaign(self):
        resp = self.client.post(
            "/api/messaging/recipients/validate/",
            data={"campaign": 999999},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_cannot_validate(self):
        self.client.logout()
        resp = self._validate()
        self.assertIn(resp.status_code, (401, 403))


class RecipientRemoveInvalidTests(RecipientApiTestBase):
    def _remove_invalid(self, campaign=None):
        return self.client.post(
            "/api/messaging/recipients/remove_invalid/",
            data={"campaign": (campaign or self.campaign).id},
            content_type="application/json",
        )

    def test_removes_only_flagged_rows(self):
        self.campaign.total = 3
        self.campaign.save(update_fields=["total"])
        good = self._recipient(email="ada@example.com", validation_status="valid")
        self._recipient(email="bad", validation_status="invalid_syntax")
        self._recipient(email="x@nope.invalid", validation_status="invalid_domain")

        resp = self._remove_invalid()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["removed"], 2)

        remaining = list(CampaignRecipient.objects.filter(campaign=self.campaign))
        self.assertEqual([r.pk for r in remaining], [good.pk])
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 1)

    def test_unknown_rows_are_not_removed(self):
        # "unknown" means never checked -- not the same as known-bad.
        row = self._recipient(validation_status="unknown")
        resp = self._remove_invalid()
        self.assertEqual(resp.json()["removed"], 0)
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_sending_campaign_marks_flagged_rows_skipped(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, email="x@nope.invalid",
                              validation_status="invalid_domain")
        resp = self._remove_invalid(campaign)
        self.assertEqual(resp.json()["removed"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")

    def test_dispatched_rows_are_reported_as_skipped_not_removed(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, email="x@nope.invalid",
                              status="sent", validation_status="invalid_domain")
        resp = self._remove_invalid(campaign)
        body = resp.json()
        self.assertEqual(body["removed"], 0)
        self.assertEqual(body["skipped"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "sent")

    def test_finished_campaign_is_rejected(self):
        campaign = self._campaign(name="Done", status="sent", total=1)
        row = self._recipient(campaign=campaign, validation_status="invalid_domain")
        resp = self._remove_invalid(campaign)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_other_campaigns_are_untouched(self):
        other = self._campaign(name="Other", total=1)
        stranger = self._recipient(campaign=other, email="x@nope.invalid",
                                   validation_status="invalid_domain")
        self._recipient(email="y@nope.invalid", validation_status="invalid_domain")
        self._remove_invalid()
        self.assertTrue(CampaignRecipient.objects.filter(pk=stranger.pk).exists())

    def test_anonymous_cannot_remove_invalid(self):
        self.client.logout()
        resp = self._remove_invalid()
        self.assertIn(resp.status_code, (401, 403))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python manage.py test messaging.tests.test_recipient_api --keepdb -v 2
```

Expected: FAIL — the two action URLs 404.

- [ ] **Step 3: Write the implementation**

Add to the imports at the top of `messaging/api.py`:

```python
from django.shortcuts import get_object_or_404

from .validation import validate_campaign_recipients
```

Add these two methods to `CampaignRecipientViewSet`, after `destroy`:

```python
    def _campaign_from_body(self, request):
        campaign_id = request.data.get("campaign")
        if not campaign_id:
            raise ValidationError({"detail": "A campaign id is required."})
        return get_object_or_404(Campaign, pk=campaign_id)

    @action(detail=False, methods=["post"])
    def validate(self, request):
        """Run the MX pass over one campaign and report the resulting counts.

        Deliberately an explicit action rather than part of building the
        audience: DNS is slow, and a list spanning many domains would otherwise
        stall the build request.
        """
        campaign = self._campaign_from_body(request)
        return Response(validate_campaign_recipients(campaign))

    @action(detail=False, methods=["post"])
    def remove_invalid(self, request):
        """Remove every flagged recipient, honouring the usual removal rules."""
        campaign = self._campaign_from_body(request)
        if campaign.status not in REMOVABLE_CAMPAIGN_STATUSES:
            return Response(
                {"detail": f"Cannot change recipients of a {campaign.status} campaign."},
                status=400,
            )

        flagged = CampaignRecipient.objects.filter(
            campaign=campaign,
            validation_status__in=["invalid_syntax", "invalid_domain"],
        ).select_related("campaign")

        removed = 0
        skipped = 0
        for recipient in flagged:
            if _remove_recipient(recipient) is None:
                removed += 1
            else:
                skipped += 1
        return Response({"removed": removed, "skipped": skipped})
```

Note the method is named `validate` on a **viewset**, not a serializer — there is no clash with DRF's serializer `validate()` hook.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
python manage.py test messaging.tests.test_recipient_api --keepdb -v 2
```

Expected: PASS — 44 tests.

- [ ] **Step 5: Run the whole messaging suite to check for regressions**

Run:

```bash
python manage.py test messaging --keepdb
```

Expected: OK, with no failures. The previously-passing 104 messaging tests plus the new ones.

- [ ] **Step 6: Commit**

```bash
git add messaging/api.py messaging/tests/test_recipient_api.py
git commit -m "feat(messaging): validate and remove_invalid recipient actions"
```

---

### Task 7: Recipients modal UI + documentation

There is no JavaScript test harness in this repository, so the automated check here is the Django template-render test; the JS itself is verified by inspection and by the reviewer's manual click-through.

**Files:**
- Create: `brand/static/brand/js/admin/recipients.js`
- Modify: `brand/templates/brand/admin/_campaigns.html` (append the modal before the closing `</div>` of `#campaigns`)
- Modify: `brand/static/brand/js/admin/campaigns.js:25-42` (the button column)
- Modify: `brand/templates/brand/admin_panel.html:225` (script tag)
- Modify: `messaging/tests/test_admin_panel_render.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: every endpoint from Tasks 4–6.
- Produces: globals `openRecipients(campaignId, campaignName)`, `closeRecipients()`, `loadRecipients()`, `addRecipient(event)`, `removeRecipient(id)`, `checkRecipientDomains()`, `removeInvalidRecipients()`.

- [ ] **Step 1: Write the failing test**

In `messaging/tests/test_admin_panel_render.py`, extend the two loops in `test_panel_renders_for_staff_with_sections`:

```python
        for anchor in [
            'id="dashboard"', 'id="blogs"', 'id="projects"', 'id="inbox"', 'id="templates"', 'id="campaigns"',
            'id="templateEditorContainer"',
            'id="templateSourceToggle"',
            'id="templatePreviewFrame"',
            'id="campaignEditorContainer"',
            'id="campaignPreviewFrame"',
            'id="recipientsModal"',
            'id="recipientsList"',
            'id="addRecipientForm"',
        ]:
            self.assertIn(anchor, html)
        for script in ['core.js', 'blogs.js', 'projects.js', 'inbox.js', 'templates.js', 'campaigns.js', 'editor.js', 'recipients.js']:
            self.assertIn(script, html)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python manage.py test messaging.tests.test_admin_panel_render --keepdb -v 2
```

Expected: FAIL — `AssertionError: 'id="recipientsModal"' not found in ...`.

- [ ] **Step 3: Add the modal markup**

In `brand/templates/brand/admin/_campaigns.html`, insert this immediately after `<div id="campaignsList" class="space-y-4"></div>` and before the final `</div>` that closes `#campaigns`:

```html
    <div id="recipientsModal" class="hidden fixed inset-0 z-50 bg-black/70 p-4 overflow-y-auto">
        <div class="max-w-3xl mx-auto my-8 bg-dark-card border border-dark-border rounded-xl">
            <div class="flex justify-between items-center px-6 py-4 border-b border-dark-border">
                <div>
                    <h3 class="text-lg font-bold text-white">Recipients</h3>
                    <p id="recipientsSubtitle" class="text-xs text-gray-500"></p>
                </div>
                <button type="button" onclick="closeRecipients()"
                    class="text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-white/5"
                    aria-label="Close recipients"><i class="fas fa-times"></i></button>
            </div>

            <div class="px-6 py-4 space-y-4">
                <div class="flex flex-wrap gap-2 items-center">
                    <input type="search" id="recipientsSearch" placeholder="Search email or name"
                        class="flex-1 min-w-[12rem] bg-[#06090F] border border-dark-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-blue">
                    <button type="button" onclick="checkRecipientDomains()"
                        class="px-3 py-2 text-xs rounded border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Check domains</button>
                    <button type="button" onclick="removeInvalidRecipients()"
                        class="px-3 py-2 text-xs rounded border border-red-900/60 text-red-400 hover:bg-red-900/20">Remove all invalid</button>
                </div>

                <div id="recipientsSummary" class="hidden text-xs text-gray-400 bg-white/5 border border-dark-border rounded px-3 py-2"></div>

                <div id="recipientsList" class="divide-y divide-dark-border border border-dark-border rounded"></div>

                <div class="flex justify-between items-center">
                    <button type="button" id="recipientsPrev" onclick="recipientsPage(-1)"
                        class="px-3 py-1.5 text-xs rounded border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Previous</button>
                    <span id="recipientsPageInfo" class="text-xs text-gray-500"></span>
                    <button type="button" id="recipientsNext" onclick="recipientsPage(1)"
                        class="px-3 py-1.5 text-xs rounded border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Next</button>
                </div>

                <form id="addRecipientForm" class="flex flex-wrap gap-2 pt-4 border-t border-dark-border">
                    <input type="email" name="email" required placeholder="add an address"
                        class="flex-1 min-w-[12rem] bg-[#06090F] border border-dark-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-blue">
                    <input type="text" name="name" placeholder="name (optional)"
                        class="flex-1 min-w-[9rem] bg-[#06090F] border border-dark-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-blue">
                    <button type="submit"
                        class="bg-brand-green hover:bg-green-500 text-black text-xs font-semibold px-4 py-2 rounded">Add</button>
                </form>
            </div>
        </div>
    </div>
```

- [ ] **Step 4: Write the modal JavaScript**

Create `brand/static/brand/js/admin/recipients.js`:

```javascript
// Campaign recipients modal: inspect, search, add and remove the individual
// addresses a campaign will mail, and flag ones that look undeliverable.

const RECIPIENTS = { campaignId: null, page: 1, search: '', hasNext: false, hasPrev: false };
let RECIPIENTS_SEARCH_TIMER = null;

const VALIDITY_BADGE = {
    valid: { label: 'valid', cls: 'text-brand-green bg-green-900/20' },
    unknown: { label: 'unchecked', cls: 'text-gray-400 bg-white/5' },
    invalid_syntax: { label: 'malformed', cls: 'text-red-400 bg-red-900/20' },
    invalid_domain: { label: 'dead domain', cls: 'text-red-400 bg-red-900/20' },
};

const SEND_BADGE = {
    pending: 'text-gray-400 bg-white/5',
    sending: 'text-yellow-400 bg-yellow-900/20',
    sent: 'text-brand-green bg-green-900/20',
    failed: 'text-red-400 bg-red-900/20',
    skipped: 'text-orange-400 bg-orange-900/20',
};

function openRecipients(campaignId, campaignName) {
    RECIPIENTS.campaignId = campaignId;
    RECIPIENTS.page = 1;
    RECIPIENTS.search = '';
    document.getElementById('recipientsSearch').value = '';
    document.getElementById('recipientsSubtitle').textContent = campaignName || '';
    document.getElementById('recipientsSummary').classList.add('hidden');
    document.getElementById('recipientsModal').classList.remove('hidden');
    loadRecipients();
}

function closeRecipients() {
    document.getElementById('recipientsModal').classList.add('hidden');
    RECIPIENTS.campaignId = null;
    // Removals and additions move campaign.total, which the card displays.
    loadCampaigns();
}

async function loadRecipients() {
    if (!RECIPIENTS.campaignId) return;
    const params = new URLSearchParams({
        campaign: RECIPIENTS.campaignId,
        page: RECIPIENTS.page,
    });
    if (RECIPIENTS.search) params.set('search', RECIPIENTS.search);

    const res = await fetch(`${API_BASE}/messaging/recipients/?${params}`, { credentials: 'same-origin' });
    const container = document.getElementById('recipientsList');
    if (!res.ok) {
        container.innerHTML = `<div class="p-4 text-sm text-red-400">Could not load recipients.</div>`;
        return;
    }
    const data = await res.json();

    container.innerHTML = data.results.length ? data.results.map(r => {
        const validity = VALIDITY_BADGE[r.validation_status] || VALIDITY_BADGE.unknown;
        const sendCls = SEND_BADGE[r.status] || 'text-gray-400 bg-white/5';
        return `
        <div class="flex items-center justify-between gap-3 px-3 py-2">
            <div class="min-w-0">
                <p class="text-sm text-white truncate">${escapeHtml(r.email)}</p>
                ${r.name ? `<p class="text-xs text-gray-500 truncate">${escapeHtml(r.name)}</p>` : ''}
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <span class="text-[10px] font-bold px-2 py-0.5 rounded uppercase ${sendCls}">${escapeHtml(r.status)}</span>
                <span class="text-[10px] font-bold px-2 py-0.5 rounded uppercase ${validity.cls}">${validity.label}</span>
                <button type="button" onclick="removeRecipient(${r.id})"
                    class="text-gray-500 hover:text-red-400 px-2 py-1 rounded hover:bg-white/5"
                    aria-label="Remove recipient"><i class="fas fa-times"></i></button>
            </div>
        </div>`;
    }).join('') : `<div class="p-4 text-sm text-gray-600 text-center">No recipients match.</div>`;

    RECIPIENTS.hasNext = Boolean(data.next);
    RECIPIENTS.hasPrev = Boolean(data.previous);
    document.getElementById('recipientsPageInfo').textContent =
        `${data.count} recipient(s) · page ${RECIPIENTS.page}`;
    document.getElementById('recipientsPrev').disabled = !RECIPIENTS.hasPrev;
    document.getElementById('recipientsNext').disabled = !RECIPIENTS.hasNext;
    document.getElementById('recipientsPrev').classList.toggle('opacity-40', !RECIPIENTS.hasPrev);
    document.getElementById('recipientsNext').classList.toggle('opacity-40', !RECIPIENTS.hasNext);
}

function recipientsPage(delta) {
    if (delta > 0 && !RECIPIENTS.hasNext) return;
    if (delta < 0 && !RECIPIENTS.hasPrev) return;
    RECIPIENTS.page += delta;
    loadRecipients();
}

async function addRecipient(event) {
    event.preventDefault();
    const form = event.target;
    const res = await fetch(`${API_BASE}/messaging/recipients/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({
            campaign: RECIPIENTS.campaignId,
            email: form.email.value,
            name: form.name.value,
        }),
    });
    if (res.ok) { form.reset(); loadRecipients(); return; }
    const data = await res.json().catch(() => ({}));
    alert(data.detail || (data.email && data.email[0]) || 'Could not add that address.');
}

async function removeRecipient(id) {
    if (!confirm('Remove this address from the campaign?')) return;
    const res = await fetch(`${API_BASE}/messaging/recipients/${id}/`, {
        method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    if (res.ok) { loadRecipients(); return; }
    const data = await res.json().catch(() => ({}));
    alert(data.detail || 'Could not remove that address.');
}

async function checkRecipientDomains() {
    const summary = document.getElementById('recipientsSummary');
    summary.classList.remove('hidden');
    summary.textContent = 'Checking domains…';
    const res = await fetch(`${API_BASE}/messaging/recipients/validate/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ campaign: RECIPIENTS.campaignId }),
    });
    if (!res.ok) { summary.textContent = 'Domain check failed.'; return; }
    const c = await res.json();
    summary.textContent =
        `${c.valid} valid · ${c.invalid_domain} dead domain · ${c.invalid_syntax} malformed · ${c.unknown} unchecked`;
    loadRecipients();
}

async function removeInvalidRecipients() {
    if (!confirm('Remove every address flagged as malformed or dead-domain?')) return;
    const res = await fetch(`${API_BASE}/messaging/recipients/remove_invalid/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ campaign: RECIPIENTS.campaignId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { alert(data.detail || 'Could not remove flagged addresses.'); return; }
    const tail = data.skipped ? ` ${data.skipped} could not be withdrawn (already sent).` : '';
    alert(`Removed ${data.removed} address(es).${tail}`);
    RECIPIENTS.page = 1;
    loadRecipients();
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addRecipientForm');
    if (form) form.addEventListener('submit', addRecipient);

    const search = document.getElementById('recipientsSearch');
    if (search) {
        search.addEventListener('input', () => {
            clearTimeout(RECIPIENTS_SEARCH_TIMER);
            RECIPIENTS_SEARCH_TIMER = setTimeout(() => {
                RECIPIENTS.search = search.value.trim();
                RECIPIENTS.page = 1;
                loadRecipients();
            }, 250);
        });
    }
});
```

- [ ] **Step 5: Add the "View recipients" button to every campaign card**

In `brand/static/brand/js/admin/campaigns.js`, inside the `<div class="flex flex-col gap-2 w-48">` block, add this line **immediately after the opening `<div ...w-48">`** and before the `${c.status === 'draft' ? ...}` block, so it appears for campaigns in every status:

```javascript
                    <button onclick="openRecipients(${c.id}, '${escapeHtml(c.name).replace(/'/g, '&#39;')}')" class="bg-dark-card border border-dark-border hover:border-brand-blue text-white text-xs px-3 py-1.5 rounded">View recipients (${c.total})</button>
```

`escapeHtml` already converts `'` to `&#39;`, so the extra `.replace` is a no-op belt-and-braces guard against the attribute-context quote — keep it, since this string is interpolated inside a single-quoted `onclick` attribute.

- [ ] **Step 6: Load the script**

In `brand/templates/brand/admin_panel.html`, after the `campaigns.js` line (line 225), add:

```html
    <script src="{% static 'brand/js/admin/recipients.js' %}" defer></script>
```

`recipients.js` must load after `core.js` (it uses `escapeHtml`, `API_BASE`, `CSRF_TOKEN`) and alongside `campaigns.js` (it calls `loadCampaigns`). Both are satisfied by appending at the end.

- [ ] **Step 7: Run the render test to verify it passes**

Run:

```bash
python manage.py test messaging.tests.test_admin_panel_render --keepdb -v 2
```

Expected: PASS.

- [ ] **Step 8: Verify no unescaped interpolation slipped in**

Run:

```bash
grep -n '${' brand/static/brand/js/admin/recipients.js | grep -v 'escapeHtml\|API_BASE\|params\|RECIPIENTS\|data\.\|c\.\|r\.id\|validity\.\|sendCls\|delta'
```

Expected: no output containing a server-supplied string rendered into `innerHTML` without `escapeHtml()`. `r.email`, `r.name` and `r.status` must each appear only wrapped in `escapeHtml(...)`. Read the matches and confirm.

- [ ] **Step 9: Document the feature**

In `README.md`, insert a new subsection immediately **before** the existing `### Email placeholders` heading:

```markdown
### Managing campaign recipients

Every campaign card has a **View recipients (N)** button that opens the
recipient list. From there you can search by email or name, add an address
by hand, and remove individual addresses.

What removal does depends on how far the campaign has got:

| Campaign status | Removing a recipient |
|---|---|
| `draft` | Deletes the row and gives the slot back (`total` decreases) |
| `queued` / `sending` / `paused` | Marks the row `skipped`; it is never emailed, and `total` is left alone so the send record stays coherent |
| `sent` / `failed` | Refused — the campaign is finished and its history is immutable |

An address that has already been sent, failed, or is in flight is never
withdrawn, whatever the campaign's status.

Adding is allowed for `draft`, `queued`, `sending` and `paused` campaigns —
a new row is simply picked up by the next outbox run. Suppressed
(unsubscribed or bounced) addresses are refused.

### Email validation

Addresses carry a validation status: `unknown`, `valid`, `invalid_syntax` or
`invalid_domain`.

- **Syntax** is checked automatically whenever recipients are built or added.
  It costs nothing and never touches the network.
- **Domains** are checked only when you press **Check domains**, which looks
  up MX records for every recipient. DNS is slow, so this is deliberately a
  button rather than something that happens during Build. Results are cached
  per domain for an hour, so a list of 500 addresses on a handful of domains
  costs a handful of lookups.

**Flagged addresses are still sent to.** The outbox does not skip them —
validation only tells you what looks undeliverable, and **Remove all
invalid** acts on it in one click. Nothing is dropped from a send without
you asking for it.
```

- [ ] **Step 10: Run the full messaging suite**

Run:

```bash
python manage.py test messaging --keepdb
```

Expected: OK, no failures.

- [ ] **Step 11: Commit**

```bash
git add brand/static/brand/js/admin/recipients.js brand/static/brand/js/admin/campaigns.js brand/templates/brand/admin/_campaigns.html brand/templates/brand/admin_panel.html messaging/tests/test_admin_panel_render.py README.md
git commit -m "feat(admin-panel): campaign recipients modal with validation controls"
```

---

## Post-implementation notes for the reviewer

- **`dnspython` is a new runtime dependency.** Any Docker image must be rebuilt (`docker compose up -d --build`) or the `validate` endpoint will 500 with `ModuleNotFoundError`.
- **No real DNS in the test suite.** Every MX test patches `messaging.validation._query_mx`. A test that omits the patch would make a live network call — treat that as a defect.
- **The MX cache is `LocMemCache` (Django's default; this project sets no `CACHES`).** It is per-process, so under gunicorn with multiple workers each worker keeps its own cache. That is acceptable — the cache is an optimisation, not a correctness requirement — but it means the lookup count in production is per-worker.
- **The send engine was not modified.** `git diff` on `messaging/management/commands/process_email_outbox.py` must be empty.
- **A manual click-through is still outstanding** for the admin panel generally; this modal is the natural thing to exercise first.
