# Contact Inbox + Bulk Mailing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a contact-inquiries inbox and a throttled bulk-email system to the custom admin panel, replacing the external Formspree contact form with a database-backed pipeline.

**Architecture:** All logic lives in a new Django app `messaging`. Inquiries are captured by a public Django endpoint. Bulk email is a database outbox (`Campaign` + `CampaignRecipient`) drained by a `process_email_outbox` management command run on cron, so sending happens outside the web request and stays under Gmail's SMTP limits. The admin panel gains staff-only Inbox/Templates/Campaigns sections that call DRF endpoints under `/api/messaging/`.

**Tech Stack:** Django, Django REST Framework, Gmail SMTP (`EmailMultiAlternatives`), `openpyxl` / `python-docx` / `pypdf` for document email extraction, Django `signing` for unsubscribe tokens. Tests use Django `TestCase` run via `python manage.py test`.

## Global Constraints

- **Working directory for all commands:** `brandtechsolution/` (contains `manage.py`). All `python manage.py` and `git` paths below are relative to the repo root unless shown otherwise; run `manage.py` from `brandtechsolution/`.
- **Test runner:** Django `TestCase`; run with `python manage.py test messaging` (NOT pytest). No pytest is installed.
- **Database:** PostgreSQL (see `config.py`). Tests create a throwaway test DB automatically.
- **DRF defaults are open** (no `REST_FRAMEWORK` block in settings ⇒ `AllowAny`). Every new admin endpoint MUST set `permission_classes = [IsAdminUser]` explicitly. Do NOT use `csrf_exempt` on new endpoints (the admin panel JS already sends `X-CSRFToken`).
- **Settings/config pattern:** new tunables go in `brandtechsolution/config.py` (`AppSettings`) with a default, then are surfaced in `settings.py` as module constants. Never read `os.environ` directly.
- **Staff gate for admin UI:** the panel view already uses `@user_passes_test(is_admin)` where `is_admin = user.is_authenticated and (user.is_staff or user.is_superuser)`. Reuse `IsAdminUser` (staff/superuser) for APIs.
- **From address:** `DEFAULT_FROM_EMAIL` (= `EMAIL_HOST_USER`). Do not hardcode.
- **Commit after every task.** Message convention: `feat(messaging): ...` / `test(messaging): ...`.

---

### Task 1: Scaffold `messaging` app + `Inquiry` model

**Files:**
- Create: `brandtechsolution/messaging/` (via `startapp`)
- Modify: `brandtechsolution/brandtechsolution/settings.py:56-67` (INSTALLED_APPS)
- Modify: `brandtechsolution/messaging/apps.py`
- Create: `brandtechsolution/messaging/models.py`
- Create: `brandtechsolution/messaging/tests/__init__.py`
- Create: `brandtechsolution/messaging/tests/test_inquiry_model.py`
- Delete: `brandtechsolution/messaging/tests.py` (replaced by tests package)

**Interfaces:**
- Produces: `messaging.models.Inquiry` with fields `name, email, phone, message, status, created_at`; status choices constant `Inquiry.STATUS_CHOICES` and values `new/read/replied/archived`.

- [ ] **Step 1: Create the app**

Run (from `brandtechsolution/`):
```bash
python manage.py startapp messaging
mkdir -p messaging/tests
rm messaging/tests.py
touch messaging/tests/__init__.py
```

- [ ] **Step 2: Register the app**

In `brandtechsolution/brandtechsolution/settings.py`, add `'messaging',` to `INSTALLED_APPS` right after `'ai_workflows',`:
```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'brand',
    'appointments',
    'ai_workflows',
    'messaging',
]
```

- [ ] **Step 3: Write the failing test**

Create `brandtechsolution/messaging/tests/test_inquiry_model.py`:
```python
from django.test import TestCase
from messaging.models import Inquiry


class InquiryModelTests(TestCase):
    def test_new_inquiry_defaults_to_new_status(self):
        inq = Inquiry.objects.create(
            name="Ada Lovelace", email="ada@example.com", message="Hello"
        )
        self.assertEqual(inq.status, "new")
        self.assertEqual(inq.phone, "")

    def test_ordering_is_newest_first(self):
        first = Inquiry.objects.create(name="A", email="a@x.com", message="m")
        second = Inquiry.objects.create(name="B", email="b@x.com", message="m")
        self.assertEqual(list(Inquiry.objects.all()), [second, first])
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python manage.py test messaging.tests.test_inquiry_model -v 2`
Expected: FAIL — `ImportError: cannot import name 'Inquiry'` (or no such model).

- [ ] **Step 5: Implement the model**

Replace `brandtechsolution/messaging/models.py` with:
```python
from django.db import models


class Inquiry(models.Model):
    STATUS_CHOICES = [
        ("new", "New"),
        ("read", "Read"),
        ("replied", "Replied"),
        ("archived", "Archived"),
    ]

    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True, default="")
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>"
```

- [ ] **Step 6: Make and run migrations**

Run:
```bash
python manage.py makemigrations messaging
python manage.py test messaging.tests.test_inquiry_model -v 2
```
Expected: migration `0001_initial` created; tests PASS.

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/messaging brandtechsolution/brandtechsolution/settings.py
git commit -m "feat(messaging): scaffold app and Inquiry model"
```

---

### Task 2: Public contact-form submission (replace Formspree)

**Files:**
- Create: `brandtechsolution/messaging/views.py` (contact_submit)
- Create: `brandtechsolution/messaging/urls.py`
- Modify: `brandtechsolution/brandtechsolution/urls.py` (include messaging public urls)
- Modify: `brandtechsolution/brand/templates/brand/contacts.html` (form action, csrf, honeypot, messages)
- Create: `brandtechsolution/messaging/tests/test_contact_submit.py`

**Interfaces:**
- Consumes: `messaging.models.Inquiry` (Task 1).
- Produces: URL name `contact_submit` at path `contacts/submit/`; view `messaging.views.contact_submit`.

- [ ] **Step 1: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_contact_submit.py`:
```python
from django.test import TestCase
from django.urls import reverse
from django.core import mail
from django.test import override_settings
from messaging.models import Inquiry


class ContactSubmitTests(TestCase):
    def _post(self, **overrides):
        data = {
            "name": "Grace Hopper",
            "email": "grace@example.com",
            "phone": "123",
            "message": "I need a website",
            "website": "",  # honeypot, must stay empty
        }
        data.update(overrides)
        return self.client.post(reverse("contact_submit"), data)

    def test_valid_submission_creates_inquiry_and_redirects(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Inquiry.objects.count(), 1)
        inq = Inquiry.objects.get()
        self.assertEqual(inq.email, "grace@example.com")
        self.assertEqual(inq.status, "new")

    def test_honeypot_filled_is_dropped_silently(self):
        resp = self._post(website="http://spam.example")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Inquiry.objects.count(), 0)

    def test_missing_required_fields_does_not_create(self):
        resp = self._post(email="", message="")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Inquiry.objects.count(), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="admin@example.com",
    )
    def test_valid_submission_sends_admin_notification(self):
        self._post()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("grace@example.com", mail.outbox[0].body)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_contact_submit -v 2`
Expected: FAIL — `NoReverseMatch: 'contact_submit' not found`.

- [ ] **Step 3: Implement the view**

Create `brandtechsolution/messaging/views.py`:
```python
from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .models import Inquiry


@require_POST
def contact_submit(request):
    """Public contact-form endpoint. Replaces the old Formspree POST target."""
    # Honeypot: real users never fill the hidden 'website' field.
    if request.POST.get("website"):
        messages.success(request, "Thanks! Your message has been sent.")
        return redirect("contacts")

    name = (request.POST.get("name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    message = (request.POST.get("message") or "").strip()

    if not (name and email and message):
        messages.error(request, "Please fill in your name, email, and message.")
        return redirect("contacts")

    inquiry = Inquiry.objects.create(
        name=name, email=email, phone=phone, message=message
    )

    try:
        send_mail(
            subject=f"New contact inquiry from {name}",
            message=f"From: {name} <{email}>\nPhone: {phone or 'n/a'}\n\n{message}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.DEFAULT_FROM_EMAIL],
            fail_silently=True,
        )
    except Exception:
        # Notification is best-effort; the inquiry is already saved.
        pass

    messages.success(request, "Thanks! Your message has been sent.")
    return redirect("contacts")
```

- [ ] **Step 4: Wire up URLs**

Create `brandtechsolution/messaging/urls.py`:
```python
from django.urls import path
from . import views

urlpatterns = [
    path("contacts/submit/", views.contact_submit, name="contact_submit"),
]
```

In `brandtechsolution/brandtechsolution/urls.py`, add to `urlpatterns` (after the `brand.urls` include):
```python
    path('', include('messaging.urls')),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test messaging.tests.test_contact_submit -v 2`
Expected: PASS (all 4).

- [ ] **Step 6: Update the contacts template**

In `brandtechsolution/brand/templates/brand/contacts.html`, find the form tag (line ~103):
```html
<form action="https://formspree.io/f/mpwvkpvk" method="POST" autocomplete="off" class="relative z-10">
```
Replace with:
```html
<form action="{% url 'contact_submit' %}" method="POST" autocomplete="off" class="relative z-10">
  {% csrf_token %}
  {% if messages %}
    {% for message in messages %}
      <div class="mb-4 rounded-lg px-4 py-3 text-sm {% if message.tags == 'error' %}bg-red-500/10 text-red-400{% else %}bg-green-500/10 text-green-400{% endif %}">{{ message }}</div>
    {% endfor %}
  {% endif %}
  <!-- Honeypot: hidden from users, bots fill it -->
  <input type="text" name="website" tabindex="-1" autocomplete="off"
         style="position:absolute;left:-9999px;top:-9999px;" aria-hidden="true">
```
Leave the existing `name`, `email`, `phone`, `message` inputs unchanged. Ensure the template extends/loads whatever it needs for `{% url %}` (it already renders via Django).

- [ ] **Step 7: Manual verification**

Run: `python manage.py runserver` and submit the form at `/contacts/`. Confirm redirect + success flash + a new `Inquiry` in the DB (`python manage.py shell -c "from messaging.models import Inquiry; print(Inquiry.objects.count())"`).

- [ ] **Step 8: Commit**

```bash
git add brandtechsolution/messaging brandtechsolution/brandtechsolution/urls.py brandtechsolution/brand/templates/brand/contacts.html
git commit -m "feat(messaging): capture contact form to DB, drop Formspree"
```

---

### Task 3: Inquiry DRF API (inbox backend)

**Files:**
- Create: `brandtechsolution/messaging/serializers.py`
- Create: `brandtechsolution/messaging/api.py`
- Create: `brandtechsolution/messaging/api_urls.py`
- Modify: `brandtechsolution/brandtechsolution/urls.py` (include `api/messaging/`)
- Create: `brandtechsolution/messaging/tests/test_inquiry_api.py`

**Interfaces:**
- Consumes: `messaging.models.Inquiry`.
- Produces: DRF router basename `inquiries` at `/api/messaging/inquiries/`; `InquirySerializer` (fields: `id, name, email, phone, message, status, created_at`). Standard `ModelViewSet` (list/retrieve/update/partial_update/destroy), `permission_classes = [IsAdminUser]`.

- [ ] **Step 1: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_inquiry_api.py`:
```python
from django.contrib.auth.models import User
from django.test import TestCase
from messaging.models import Inquiry


class InquiryApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.inq = Inquiry.objects.create(name="A", email="a@x.com", message="m")

    def test_anonymous_cannot_list(self):
        resp = self.client.get("/api/messaging/inquiries/")
        self.assertIn(resp.status_code, (401, 403))

    def test_staff_can_list(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/api/messaging/inquiries/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_staff_can_update_status(self):
        self.client.force_login(self.staff)
        resp = self.client.patch(
            f"/api/messaging/inquiries/{self.inq.id}/",
            data={"status": "read"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.inq.refresh_from_db()
        self.assertEqual(self.inq.status, "read")

    def test_staff_can_delete(self):
        self.client.force_login(self.staff)
        resp = self.client.delete(f"/api/messaging/inquiries/{self.inq.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Inquiry.objects.count(), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_inquiry_api -v 2`
Expected: FAIL — 404 (URL not routed).

- [ ] **Step 3: Implement serializer**

Create `brandtechsolution/messaging/serializers.py`:
```python
from rest_framework import serializers
from .models import Inquiry


class InquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = ["id", "name", "email", "phone", "message", "status", "created_at"]
        read_only_fields = ["id", "name", "email", "phone", "message", "created_at"]
```

- [ ] **Step 4: Implement viewset**

Create `brandtechsolution/messaging/api.py`:
```python
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

from .models import Inquiry
from .serializers import InquirySerializer


class InquiryViewSet(viewsets.ModelViewSet):
    queryset = Inquiry.objects.all()
    serializer_class = InquirySerializer
    permission_classes = [IsAdminUser]
```

- [ ] **Step 5: Wire up API urls**

Create `brandtechsolution/messaging/api_urls.py`:
```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api

router = DefaultRouter()
router.register(r"inquiries", api.InquiryViewSet, basename="inquiries")

urlpatterns = [
    path("", include(router.urls)),
]
```

In `brandtechsolution/brandtechsolution/urls.py`, add to `urlpatterns` (near the other `api/` includes):
```python
    path('api/messaging/', include('messaging.api_urls')),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test messaging.tests.test_inquiry_api -v 2`
Expected: PASS (all 4).

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/messaging brandtechsolution/brandtechsolution/urls.py
git commit -m "feat(messaging): staff-only Inquiry inbox API"
```

---

### Task 4: EmailTemplate model + API

**Files:**
- Modify: `brandtechsolution/messaging/models.py` (add EmailTemplate)
- Modify: `brandtechsolution/messaging/serializers.py` (add EmailTemplateSerializer)
- Modify: `brandtechsolution/messaging/api.py` (add EmailTemplateViewSet)
- Modify: `brandtechsolution/messaging/api_urls.py` (register templates)
- Create: `brandtechsolution/messaging/tests/test_template_api.py`

**Interfaces:**
- Produces: `messaging.models.EmailTemplate` (`name, subject, body_html, created_at, updated_at`); route `/api/messaging/templates/`, basename `templates`; `EmailTemplateSerializer` (all fields).

- [ ] **Step 1: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_template_api.py`:
```python
from django.contrib.auth.models import User
from django.test import TestCase
from messaging.models import EmailTemplate


class EmailTemplateApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def test_anonymous_cannot_create(self):
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "Welcome", "subject": "Hi", "body_html": "<p>Hi {{ name }}</p>",
        })
        self.assertIn(resp.status_code, (401, 403))

    def test_staff_can_create_and_list(self):
        self.client.force_login(self.staff)
        resp = self.client.post("/api/messaging/templates/", data={
            "name": "Welcome", "subject": "Hi", "body_html": "<p>Hi {{ name }}</p>",
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(EmailTemplate.objects.count(), 1)
        resp = self.client.get("/api/messaging/templates/")
        self.assertEqual(len(resp.json()), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_template_api -v 2`
Expected: FAIL — model/route missing.

- [ ] **Step 3: Add the model**

Append to `brandtechsolution/messaging/models.py`:
```python
class EmailTemplate(models.Model):
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=255)
    body_html = models.TextField(help_text="HTML body. Supports {{ name }} and {{ unsubscribe_url }}.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
```

- [ ] **Step 4: Add serializer and viewset**

Append to `brandtechsolution/messaging/serializers.py`:
```python
from .models import EmailTemplate  # noqa: E402  (grouped import; keep near top if preferred)


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ["id", "name", "subject", "body_html", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
```
(If your linter dislikes the mid-file import, move `EmailTemplate` into the existing `from .models import ...` line at the top.)

Append to `brandtechsolution/messaging/api.py`:
```python
from .models import EmailTemplate
from .serializers import EmailTemplateSerializer


class EmailTemplateViewSet(viewsets.ModelViewSet):
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer
    permission_classes = [IsAdminUser]
```

- [ ] **Step 5: Register the route**

In `brandtechsolution/messaging/api_urls.py`, add:
```python
router.register(r"templates", api.EmailTemplateViewSet, basename="templates")
```

- [ ] **Step 6: Migrate and run tests**

Run:
```bash
python manage.py makemigrations messaging
python manage.py test messaging.tests.test_template_api -v 2
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): EmailTemplate model and API"
```

---

### Task 5: Suppression model + unsubscribe endpoint

**Files:**
- Modify: `brandtechsolution/messaging/models.py` (add Suppression)
- Create: `brandtechsolution/messaging/tokens.py`
- Modify: `brandtechsolution/messaging/views.py` (add unsubscribe view)
- Modify: `brandtechsolution/messaging/urls.py` (add unsubscribe route)
- Create: `brandtechsolution/messaging/tests/test_unsubscribe.py`

**Interfaces:**
- Produces:
  - `messaging.models.Suppression` (`email` unique, `reason`, `created_at`); `Suppression.REASON_CHOICES`.
  - `messaging.tokens.make_unsubscribe_token(email) -> str` and `read_unsubscribe_token(token) -> str` (raises `django.core.signing.BadSignature` on tamper).
  - URL name `unsubscribe` at `unsubscribe/<str:token>/`.

- [ ] **Step 1: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_unsubscribe.py`:
```python
from django.test import TestCase
from django.urls import reverse
from messaging.models import Suppression
from messaging.tokens import make_unsubscribe_token


class UnsubscribeTests(TestCase):
    def test_valid_token_adds_suppression(self):
        token = make_unsubscribe_token("bob@example.com")
        resp = self.client.get(reverse("unsubscribe", args=[token]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Suppression.objects.filter(email="bob@example.com").exists())

    def test_unsubscribe_is_idempotent(self):
        token = make_unsubscribe_token("bob@example.com")
        self.client.get(reverse("unsubscribe", args=[token]))
        self.client.get(reverse("unsubscribe", args=[token]))
        self.assertEqual(Suppression.objects.filter(email="bob@example.com").count(), 1)

    def test_tampered_token_is_rejected(self):
        resp = self.client.get(reverse("unsubscribe", args=["not-a-valid-token"]))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Suppression.objects.count(), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_unsubscribe -v 2`
Expected: FAIL — `tokens` module / route missing.

- [ ] **Step 3: Add the Suppression model**

Append to `brandtechsolution/messaging/models.py`:
```python
class Suppression(models.Model):
    REASON_CHOICES = [
        ("unsubscribed", "Unsubscribed"),
        ("bounced", "Bounced"),
        ("manual", "Manual"),
    ]
    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default="unsubscribed")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.email} ({self.reason})"
```

- [ ] **Step 4: Add the token helpers**

Create `brandtechsolution/messaging/tokens.py`:
```python
from django.core import signing

_SALT = "messaging.unsubscribe"


def make_unsubscribe_token(email: str) -> str:
    return signing.dumps(email.strip().lower(), salt=_SALT)


def read_unsubscribe_token(token: str) -> str:
    """Return the email encoded in the token. Raises signing.BadSignature if invalid."""
    return signing.loads(token, salt=_SALT)
```

- [ ] **Step 5: Add the unsubscribe view**

Append to `brandtechsolution/messaging/views.py`:
```python
from django.core import signing
from django.http import HttpResponse

from .models import Suppression
from .tokens import read_unsubscribe_token


def unsubscribe(request, token):
    try:
        email = read_unsubscribe_token(token)
    except signing.BadSignature:
        return HttpResponse("Invalid or expired unsubscribe link.", status=400)

    Suppression.objects.get_or_create(email=email, defaults={"reason": "unsubscribed"})
    return HttpResponse(
        "<h1>You've been unsubscribed</h1>"
        "<p>You will no longer receive bulk emails from us.</p>",
        status=200,
    )
```

- [ ] **Step 6: Add the route**

In `brandtechsolution/messaging/urls.py`, add to `urlpatterns`:
```python
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
```

- [ ] **Step 7: Migrate and run tests**

Run:
```bash
python manage.py makemigrations messaging
python manage.py test messaging.tests.test_unsubscribe -v 2
```
Expected: PASS (all 3).

- [ ] **Step 8: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): suppression list and signed unsubscribe endpoint"
```

---

### Task 6: Campaign + CampaignRecipient models

**Files:**
- Modify: `brandtechsolution/messaging/models.py` (add Campaign, CampaignRecipient)
- Create: `brandtechsolution/messaging/tests/test_campaign_models.py`

**Interfaces:**
- Produces:
  - `messaging.models.Campaign` — fields `name, subject, body_html, template (FK, null), status, total, sent_count, failed_count, created_by (FK User, null), created_at, started_at (null), completed_at (null)`; `Campaign.STATUS_CHOICES` with values `draft/queued/sending/sent/paused/failed`.
  - `messaging.models.CampaignRecipient` — fields `campaign (FK, related_name='recipients'), email, name, status, attempts, error, sent_at (null)`; `CampaignRecipient.STATUS_CHOICES` values `pending/sent/failed/skipped`; `unique_together = ('campaign', 'email')`.

- [ ] **Step 1: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_campaign_models.py`:
```python
from django.db import IntegrityError
from django.test import TestCase
from messaging.models import Campaign, CampaignRecipient


class CampaignModelTests(TestCase):
    def test_campaign_defaults(self):
        c = Campaign.objects.create(name="Launch", subject="Hi", body_html="<p>x</p>")
        self.assertEqual(c.status, "draft")
        self.assertEqual(c.total, 0)
        self.assertEqual(c.sent_count, 0)
        self.assertIsNone(c.started_at)

    def test_recipient_defaults_and_uniqueness(self):
        c = Campaign.objects.create(name="Launch", subject="Hi", body_html="<p>x</p>")
        r = CampaignRecipient.objects.create(campaign=c, email="a@x.com", name="A")
        self.assertEqual(r.status, "pending")
        self.assertEqual(r.attempts, 0)
        with self.assertRaises(IntegrityError):
            CampaignRecipient.objects.create(campaign=c, email="a@x.com")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_campaign_models -v 2`
Expected: FAIL — models missing.

- [ ] **Step 3: Add the models**

Append to `brandtechsolution/messaging/models.py`:
```python
from django.conf import settings


class Campaign(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("queued", "Queued"),
        ("sending", "Sending"),
        ("sent", "Sent"),
        ("paused", "Paused"),
        ("failed", "Failed"),
    ]
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=255)
    body_html = models.TextField()
    template = models.ForeignKey(
        "EmailTemplate", null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    total = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class CampaignRecipient(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    ]
    campaign = models.ForeignKey(
        Campaign, related_name="recipients", on_delete=models.CASCADE
    )
    email = models.EmailField()
    name = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("campaign", "email")
        indexes = [models.Index(fields=["campaign", "status"])]

    def __str__(self):
        return f"{self.email} [{self.status}]"
```

- [ ] **Step 4: Migrate and run tests**

Run:
```bash
python manage.py makemigrations messaging
python manage.py test messaging.tests.test_campaign_models -v 2
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): Campaign and CampaignRecipient models"
```

---

### Task 7: Audience resolution

**Files:**
- Create: `brandtechsolution/messaging/audience.py`
- Create: `brandtechsolution/messaging/tests/test_audience.py`

**Interfaces:**
- Consumes: `Inquiry`, `Suppression`, `CampaignRecipient`, `Campaign` (Tasks 1/5/6); `auth.User`; `appointments.models.Appointment`.
- Produces:
  - `messaging.audience.SOURCE_KEYS = {"inquiries", "users", "appointments"}`.
  - `messaging.audience.resolve_recipients(source_keys: list[str], manual_emails: list[str]) -> list[dict]` — each dict `{"email": str, "name": str}`, lowercased + deduped by email, excluding suppressed addresses.
  - `messaging.audience.build_recipients(campaign, source_keys, manual_emails) -> int` — creates `CampaignRecipient` rows, sets `campaign.total`, returns count.

- [ ] **Step 1: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_audience.py`:
```python
from django.contrib.auth.models import User
from django.test import TestCase
from appointments.models import Appointment
from messaging.models import Campaign, CampaignRecipient, Inquiry, Suppression
from messaging import audience


class AudienceTests(TestCase):
    def setUp(self):
        Inquiry.objects.create(name="Ada", email="ada@x.com", message="m")
        User.objects.create_user("u1", email="user@x.com", password="p")
        Appointment.objects.create(
            email="client@x.com", phone="1", full_name="Client C",
            title="t", description="d", date="2026-01-01", time="10:00",
            estimated_duration=30,
        )

    def test_resolve_merges_and_dedupes(self):
        result = audience.resolve_recipients(
            ["inquiries", "users", "appointments"],
            manual_emails=["ada@x.com", "Extra@X.com"],  # dupe of ada + one new
        )
        emails = sorted(r["email"] for r in result)
        self.assertEqual(
            emails, ["ada@x.com", "client@x.com", "extra@x.com", "user@x.com"]
        )

    def test_resolve_excludes_suppressed(self):
        Suppression.objects.create(email="ada@x.com")
        result = audience.resolve_recipients(["inquiries"], manual_emails=[])
        self.assertEqual(result, [])

    def test_resolve_populates_name_from_source(self):
        result = audience.resolve_recipients(["appointments"], manual_emails=[])
        self.assertEqual(result[0]["name"], "Client C")

    def test_build_recipients_creates_rows_and_sets_total(self):
        c = Campaign.objects.create(name="C", subject="s", body_html="<p>x</p>")
        n = audience.build_recipients(c, ["inquiries"], manual_emails=["new@x.com"])
        c.refresh_from_db()
        self.assertEqual(n, 2)
        self.assertEqual(c.total, 2)
        self.assertEqual(CampaignRecipient.objects.filter(campaign=c).count(), 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_audience -v 2`
Expected: FAIL — `audience` module missing.

- [ ] **Step 3: Implement audience resolution**

Create `brandtechsolution/messaging/audience.py`:
```python
from django.contrib.auth.models import User

from appointments.models import Appointment
from .models import CampaignRecipient, Inquiry, Suppression

SOURCE_KEYS = {"inquiries", "users", "appointments"}


def _iter_source(key):
    """Yield (email, name) pairs for a source key."""
    if key == "inquiries":
        for name, email in Inquiry.objects.values_list("name", "email"):
            yield email, name
    elif key == "users":
        for first, last, email in User.objects.exclude(email="").values_list(
            "first_name", "last_name", "email"
        ):
            yield email, (f"{first} {last}".strip())
    elif key == "appointments":
        for name, email in Appointment.objects.values_list("full_name", "email"):
            yield email, name


def resolve_recipients(source_keys, manual_emails):
    """Merge selected sources + manual list into deduped, suppression-filtered dicts."""
    suppressed = set(Suppression.objects.values_list("email", flat=True))
    merged = {}  # email(lower) -> name

    for key in source_keys:
        if key not in SOURCE_KEYS:
            continue
        for email, name in _iter_source(key):
            if not email:
                continue
            e = email.strip().lower()
            merged.setdefault(e, (name or "").strip())

    for email in manual_emails or []:
        e = (email or "").strip().lower()
        if e:
            merged.setdefault(e, "")

    return [
        {"email": e, "name": n}
        for e, n in merged.items()
        if e not in suppressed
    ]


def build_recipients(campaign, source_keys, manual_emails):
    """Materialize resolved recipients as CampaignRecipient rows; set campaign.total."""
    recipients = resolve_recipients(source_keys, manual_emails)
    CampaignRecipient.objects.bulk_create(
        [
            CampaignRecipient(campaign=campaign, email=r["email"], name=r["name"])
            for r in recipients
        ],
        ignore_conflicts=True,
    )
    count = CampaignRecipient.objects.filter(campaign=campaign).count()
    campaign.total = count
    campaign.save(update_fields=["total"])
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test messaging.tests.test_audience -v 2`
Expected: PASS (all 4).

- [ ] **Step 5: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): audience resolution with dedup and suppression"
```

---

### Task 8: Document email extraction

**Files:**
- Create: `brandtechsolution/messaging/imports.py`
- Modify: `requirements.txt` (add `openpyxl`, `python-docx`, `pypdf`)
- Create: `brandtechsolution/messaging/tests/test_imports.py`

**Interfaces:**
- Produces:
  - `messaging.imports.extract_emails_from_file(uploaded_file) -> list[str]` — dispatches by lowercased filename extension; returns deduped, validated, lowercased emails.
  - `messaging.imports.SUPPORTED_EXTENSIONS = {".csv", ".txt", ".xlsx", ".pdf", ".docx"}`.
  - `messaging.imports.UnsupportedFileType(Exception)`.

- [ ] **Step 1: Install dependencies**

Add to `requirements.txt`:
```
openpyxl
python-docx
pypdf
```
Run: `pip install openpyxl python-docx pypdf`

- [ ] **Step 2: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_imports.py`:
```python
import io
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from messaging import imports
from messaging.imports import UnsupportedFileType


class ImportTests(TestCase):
    def test_txt_extraction_dedupes_and_lowercases(self):
        content = b"Reach me at Alice@Example.com or bob@x.com. Again: alice@example.com"
        f = SimpleUploadedFile("contacts.txt", content, content_type="text/plain")
        self.assertEqual(
            sorted(imports.extract_emails_from_file(f)),
            ["alice@example.com", "bob@x.com"],
        )

    def test_csv_extraction(self):
        content = b"name,email\nAda,ada@x.com\nBob,bob@x.com\n"
        f = SimpleUploadedFile("list.csv", content, content_type="text/csv")
        self.assertEqual(
            sorted(imports.extract_emails_from_file(f)), ["ada@x.com", "bob@x.com"]
        )

    def test_xlsx_extraction(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "email"])
        ws.append(["Ada", "ada@x.com"])
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile(
            "list.xlsx", buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(imports.extract_emails_from_file(f), ["ada@x.com"])

    def test_docx_extraction(self):
        import docx
        doc = docx.Document()
        doc.add_paragraph("Contact ada@x.com for details.")
        buf = io.BytesIO()
        doc.save(buf)
        f = SimpleUploadedFile(
            "list.docx", buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(imports.extract_emails_from_file(f), ["ada@x.com"])

    def test_unsupported_type_raises(self):
        f = SimpleUploadedFile("photo.png", b"\x89PNG", content_type="image/png")
        with self.assertRaises(UnsupportedFileType):
            imports.extract_emails_from_file(f)
```
(PDF path is covered by manual verification in Step 5 to avoid brittle binary fixtures; the code path is implemented and shares the same regex.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_imports -v 2`
Expected: FAIL — `imports` module missing.

- [ ] **Step 4: Implement the extractor**

Create `brandtechsolution/messaging/imports.py`:
```python
import os
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
SUPPORTED_EXTENSIONS = {".csv", ".txt", ".xlsx", ".pdf", ".docx"}


class UnsupportedFileType(Exception):
    pass


def _emails_from_text(text):
    return EMAIL_RE.findall(text or "")


def _text_from_txt(f):
    return f.read().decode("utf-8", errors="ignore")


def _text_from_xlsx(f):
    import openpyxl
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for cell in row:
                if cell is not None:
                    parts.append(str(cell))
    return " ".join(parts)


def _text_from_pdf(f):
    from pypdf import PdfReader
    reader = PdfReader(f)
    return " ".join((page.extract_text() or "") for page in reader.pages)


def _text_from_docx(f):
    import docx
    document = docx.Document(f)
    return " ".join(p.text for p in document.paragraphs)


_EXTRACTORS = {
    ".txt": _text_from_txt,
    ".csv": _text_from_txt,
    ".xlsx": _text_from_xlsx,
    ".pdf": _text_from_pdf,
    ".docx": _text_from_docx,
}


def extract_emails_from_file(uploaded_file):
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(ext)
    text = _EXTRACTORS[ext](uploaded_file)
    seen = {}
    for email in _emails_from_text(text):
        seen.setdefault(email.lower(), None)
    return list(seen.keys())
```

- [ ] **Step 5: Run tests + manual PDF check**

Run: `python manage.py test messaging.tests.test_imports -v 2`
Expected: PASS (all 5).
Then manually verify PDF once in a shell:
```bash
python manage.py shell -c "
from pypdf import PdfWriter; import io
# If you have a PDF containing an email, load it and confirm extraction:
from messaging.imports import extract_emails_from_file
"
```
(If no PDF is handy, skip — the shared regex path is exercised by the other formats.)

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/messaging requirements.txt
git commit -m "feat(messaging): extract emails from csv/txt/xlsx/pdf/docx uploads"
```

---

### Task 9: Extract-emails API endpoint

**Files:**
- Modify: `brandtechsolution/messaging/api.py` (add extract_emails view)
- Modify: `brandtechsolution/messaging/api_urls.py` (add route)
- Create: `brandtechsolution/messaging/tests/test_extract_api.py`

**Interfaces:**
- Consumes: `messaging.imports.extract_emails_from_file`, `UnsupportedFileType`.
- Produces: `POST /api/messaging/extract-emails/` (multipart, field `file`), staff-only, returns `{"emails": [...], "count": N}`. Rejects files over `MAX_IMPORT_BYTES = 5 * 1024 * 1024` (400) and unsupported types (400).

- [ ] **Step 1: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_extract_api.py`:
```python
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase


class ExtractApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def _file(self):
        return SimpleUploadedFile("c.txt", b"a@x.com b@x.com", content_type="text/plain")

    def test_anonymous_forbidden(self):
        resp = self.client.post("/api/messaging/extract-emails/", {"file": self._file()})
        self.assertIn(resp.status_code, (401, 403))

    def test_staff_extracts_emails(self):
        self.client.force_login(self.staff)
        resp = self.client.post("/api/messaging/extract-emails/", {"file": self._file()})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(sorted(resp.json()["emails"]), ["a@x.com", "b@x.com"])
        self.assertEqual(resp.json()["count"], 2)

    def test_unsupported_type_rejected(self):
        self.client.force_login(self.staff)
        f = SimpleUploadedFile("p.png", b"\x89PNG", content_type="image/png")
        resp = self.client.post("/api/messaging/extract-emails/", {"file": f})
        self.assertEqual(resp.status_code, 400)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_extract_api -v 2`
Expected: FAIL — route missing.

- [ ] **Step 3: Implement the endpoint**

Append to `brandtechsolution/messaging/api.py`:
```python
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from .imports import extract_emails_from_file, UnsupportedFileType

MAX_IMPORT_BYTES = 5 * 1024 * 1024


@api_view(["POST"])
@permission_classes([IsAdminUser])
@parser_classes([MultiPartParser])
def extract_emails(request):
    upload = request.FILES.get("file")
    if not upload:
        return Response({"detail": "No file provided."}, status=400)
    if upload.size > MAX_IMPORT_BYTES:
        return Response({"detail": "File too large (max 5MB)."}, status=400)
    try:
        emails = extract_emails_from_file(upload)
    except UnsupportedFileType:
        return Response({"detail": "Unsupported file type."}, status=400)
    except Exception:
        return Response({"detail": "Could not parse file."}, status=400)
    return Response({"emails": emails, "count": len(emails)})
```

- [ ] **Step 4: Add the route**

In `brandtechsolution/messaging/api_urls.py`, add to `urlpatterns` (alongside the router include):
```python
    path("extract-emails/", api.extract_emails, name="extract-emails"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test messaging.tests.test_extract_api -v 2`
Expected: PASS (all 3).

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): staff-only extract-emails upload endpoint"
```

---

### Task 10: Campaign API — create / build recipients / queue

**Files:**
- Modify: `brandtechsolution/messaging/serializers.py` (CampaignSerializer)
- Modify: `brandtechsolution/messaging/api.py` (CampaignViewSet with build_recipients + queue actions)
- Modify: `brandtechsolution/messaging/api_urls.py` (register campaigns)
- Create: `brandtechsolution/messaging/tests/test_campaign_api.py`

**Interfaces:**
- Consumes: `Campaign`, `CampaignRecipient`, `audience.build_recipients`.
- Produces:
  - `/api/messaging/campaigns/` (basename `campaigns`) standard CRUD, `IsAdminUser`.
  - `CampaignSerializer` fields: `id, name, subject, body_html, template, status, total, sent_count, failed_count, created_at, started_at, completed_at` (counters + status read-only).
  - Detail action `POST /api/messaging/campaigns/<id>/build_recipients/` body `{"sources": [...], "manual_emails": [...]}` → `{"count": N}`; only allowed while `status == "draft"`.
  - Detail action `POST /api/messaging/campaigns/<id>/queue/` → sets `status="queued"`; 400 if no recipients or not draft.

- [ ] **Step 1: Write the failing tests**

Create `brandtechsolution/messaging/tests/test_campaign_api.py`:
```python
from django.contrib.auth.models import User
from django.test import TestCase
from messaging.models import Campaign, CampaignRecipient, Inquiry


class CampaignApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.client.force_login(self.staff)
        Inquiry.objects.create(name="Ada", email="ada@x.com", message="m")

    def _make_campaign(self):
        resp = self.client.post("/api/messaging/campaigns/", data={
            "name": "Launch", "subject": "Hello", "body_html": "<p>Hi {{ name }}</p>",
        })
        self.assertEqual(resp.status_code, 201)
        return resp.json()["id"]

    def test_create_campaign_is_draft(self):
        cid = self._make_campaign()
        self.assertEqual(Campaign.objects.get(id=cid).status, "draft")

    def test_build_recipients_action(self):
        cid = self._make_campaign()
        resp = self.client.post(
            f"/api/messaging/campaigns/{cid}/build_recipients/",
            data={"sources": ["inquiries"], "manual_emails": ["new@x.com"]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)
        self.assertEqual(CampaignRecipient.objects.filter(campaign_id=cid).count(), 2)

    def test_queue_requires_recipients(self):
        cid = self._make_campaign()
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/queue/")
        self.assertEqual(resp.status_code, 400)

    def test_queue_sets_status(self):
        cid = self._make_campaign()
        self.client.post(
            f"/api/messaging/campaigns/{cid}/build_recipients/",
            data={"sources": ["inquiries"], "manual_emails": []},
            content_type="application/json",
        )
        resp = self.client.post(f"/api/messaging/campaigns/{cid}/queue/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Campaign.objects.get(id=cid).status, "queued")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_campaign_api -v 2`
Expected: FAIL — route/actions missing.

- [ ] **Step 3: Add the serializer**

Append to `brandtechsolution/messaging/serializers.py`:
```python
from .models import Campaign


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "id", "name", "subject", "body_html", "template", "status",
            "total", "sent_count", "failed_count",
            "created_at", "started_at", "completed_at",
        ]
        read_only_fields = [
            "id", "status", "total", "sent_count", "failed_count",
            "created_at", "started_at", "completed_at",
        ]
```

- [ ] **Step 4: Add the viewset + actions**

Append to `brandtechsolution/messaging/api.py`:
```python
from rest_framework.decorators import action

from .models import Campaign
from .serializers import CampaignSerializer
from . import audience


class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer
    permission_classes = [IsAdminUser]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def build_recipients(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != "draft":
            return Response(
                {"detail": "Recipients can only be built for a draft campaign."},
                status=400,
            )
        sources = request.data.get("sources", []) or []
        manual = request.data.get("manual_emails", []) or []
        count = audience.build_recipients(campaign, sources, manual)
        return Response({"count": count})

    @action(detail=True, methods=["post"])
    def queue(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != "draft":
            return Response({"detail": "Only draft campaigns can be queued."}, status=400)
        if campaign.total == 0:
            return Response({"detail": "No recipients. Build recipients first."}, status=400)
        campaign.status = "queued"
        campaign.save(update_fields=["status"])
        return Response({"status": campaign.status})
```

- [ ] **Step 5: Register the route**

In `brandtechsolution/messaging/api_urls.py`, add:
```python
router.register(r"campaigns", api.CampaignViewSet, basename="campaigns")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test messaging.tests.test_campaign_api -v 2`
Expected: PASS (all 4).

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): campaign CRUD, build-recipients and queue actions"
```

---

### Task 11: Send engine — `process_email_outbox` command

**Files:**
- Modify: `brandtechsolution/brandtechsolution/config.py` (outbox settings)
- Modify: `brandtechsolution/brandtechsolution/settings.py` (surface constants)
- Create: `brandtechsolution/messaging/rendering.py` (placeholder rendering + plain-text)
- Create: `brandtechsolution/messaging/management/__init__.py`
- Create: `brandtechsolution/messaging/management/commands/__init__.py`
- Create: `brandtechsolution/messaging/management/commands/process_email_outbox.py`
- Create: `brandtechsolution/messaging/tests/test_send_engine.py`

**Interfaces:**
- Consumes: `Campaign`, `CampaignRecipient`, `Suppression`, `tokens.make_unsubscribe_token`.
- Produces:
  - `settings.OUTBOX_BATCH_SIZE` (int, default 50), `settings.OUTBOX_MAX_ATTEMPTS` (int, default 3).
  - `messaging.rendering.render_body(body_html, name, unsubscribe_url) -> str` and `render_subject(subject, name) -> str`; `html_to_text(html) -> str`.
  - Management command `process_email_outbox` that drains `queued`/`sending` campaigns in batches.

- [ ] **Step 1: Add config + settings constants**

In `brandtechsolution/brandtechsolution/config.py`, add to `AppSettings` (after the Email block):
```python
    # ============================================================
    # Bulk mail outbox
    # ============================================================
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 3
    site_base_url: str = "https://teklora.co.ke"
```
In `brandtechsolution/brandtechsolution/settings.py`, after the email settings block (~line 186), add:
```python
OUTBOX_BATCH_SIZE = config.outbox_batch_size
OUTBOX_MAX_ATTEMPTS = config.outbox_max_attempts
SITE_BASE_URL = config.site_base_url
```

- [ ] **Step 2: Write the rendering helper (with tests)**

Create `brandtechsolution/messaging/tests/test_rendering.py`:
```python
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
```
Run: `python manage.py test messaging.tests.test_rendering -v 2` → FAIL.

Create `brandtechsolution/messaging/rendering.py`:
```python
import re


def render_subject(subject, name):
    return (subject or "").replace("{{ name }}", name or "").replace("{{name}}", name or "")


def render_body(body_html, name, unsubscribe_url):
    out = body_html or ""
    for token, value in (
        ("{{ name }}", name or ""),
        ("{{name}}", name or ""),
        ("{{ unsubscribe_url }}", unsubscribe_url or ""),
        ("{{unsubscribe_url}}", unsubscribe_url or ""),
    ):
        out = out.replace(token, value)
    return out


def html_to_text(html):
    text = re.sub(r"<[^>]+>", "", html or "")
    return re.sub(r"[ \t]+", " ", text)
```
Run again → PASS.

- [ ] **Step 3: Write the failing send-engine tests**

Create `brandtechsolution/messaging/tests/test_send_engine.py`:
```python
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from messaging.models import Campaign, CampaignRecipient, Suppression


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="admin@example.com",
    OUTBOX_BATCH_SIZE=50,
    OUTBOX_MAX_ATTEMPTS=3,
)
class SendEngineTests(TestCase):
    def _campaign(self, status="queued"):
        c = Campaign.objects.create(
            name="C", subject="Hi {{ name }}", body_html="<p>Hi {{ name }}</p>",
            status=status, total=0,
        )
        return c

    def test_sends_pending_and_marks_sent(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com", name="Ada")
        c.total = 1
        c.save(update_fields=["total"])
        call_command("process_email_outbox")
        r = CampaignRecipient.objects.get(campaign=c)
        c.refresh_from_db()
        self.assertEqual(r.status, "sent")
        self.assertEqual(c.status, "sent")
        self.assertEqual(c.sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Ada", mail.outbox[0].subject)

    def test_skips_suppressed(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com")
        c.total = 1
        c.save(update_fields=["total"])
        Suppression.objects.create(email="a@x.com")
        call_command("process_email_outbox")
        r = CampaignRecipient.objects.get(campaign=c)
        self.assertEqual(r.status, "skipped")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(OUTBOX_BATCH_SIZE=1)
    def test_batch_size_limits_per_run(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com")
        CampaignRecipient.objects.create(campaign=c, email="b@x.com")
        c.total = 2
        c.save(update_fields=["total"])
        call_command("process_email_outbox")
        sent = CampaignRecipient.objects.filter(campaign=c, status="sent").count()
        self.assertEqual(sent, 1)
        c.refresh_from_db()
        self.assertEqual(c.status, "sending")  # not done yet

    def test_failed_send_retries_then_fails(self):
        c = self._campaign()
        CampaignRecipient.objects.create(campaign=c, email="a@x.com")
        c.total = 1
        c.save(update_fields=["total"])
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="127.0.0.1", EMAIL_PORT=1,  # unreachable → send raises
        ):
            for _ in range(3):
                call_command("process_email_outbox")
        r = CampaignRecipient.objects.get(campaign=c)
        c.refresh_from_db()
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.attempts, 3)
        self.assertEqual(c.status, "failed")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python manage.py test messaging.tests.test_send_engine -v 2`
Expected: FAIL — command missing.

- [ ] **Step 5: Implement the command**

Create the package dirs and `brandtechsolution/messaging/management/commands/process_email_outbox.py`:
```python
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from messaging.models import Campaign, CampaignRecipient, Suppression
from messaging.rendering import render_body, render_subject, html_to_text
from messaging.tokens import make_unsubscribe_token


class Command(BaseCommand):
    help = "Send a batch of pending bulk emails from queued/sending campaigns."

    def handle(self, *args, **options):
        batch_size = settings.OUTBOX_BATCH_SIZE
        max_attempts = settings.OUTBOX_MAX_ATTEMPTS
        suppressed = set(Suppression.objects.values_list("email", flat=True))

        campaigns = Campaign.objects.filter(status__in=["queued", "sending"])
        connection = get_connection()

        for campaign in campaigns:
            if campaign.status == "queued":
                campaign.status = "sending"
                if campaign.started_at is None:
                    campaign.started_at = timezone.now()
                campaign.save(update_fields=["status", "started_at"])

            pending = list(
                campaign.recipients.filter(status="pending").order_by("id")[:batch_size]
            )

            for recipient in pending:
                if recipient.email in suppressed:
                    recipient.status = "skipped"
                    recipient.save(update_fields=["status"])
                    continue
                self._send_one(campaign, recipient, connection, max_attempts)

            self._maybe_complete(campaign)

    def _send_one(self, campaign, recipient, connection, max_attempts):
        token = make_unsubscribe_token(recipient.email)
        unsubscribe_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
            "unsubscribe", args=[token]
        )
        subject = render_subject(campaign.subject, recipient.name)
        html_body = render_body(campaign.body_html, recipient.name, unsubscribe_url)
        text_body = html_to_text(html_body)

        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient.email],
                connection=connection,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send()
        except Exception as exc:  # noqa: BLE001 - record and retry/fail
            recipient.attempts += 1
            recipient.error = str(exc)[:1000]
            if recipient.attempts >= max_attempts:
                recipient.status = "failed"
                recipient.save(update_fields=["attempts", "error", "status"])
                Campaign.objects.filter(pk=campaign.pk).update(
                    failed_count=campaign.__class__.objects.get(pk=campaign.pk).failed_count + 1
                )
            else:
                recipient.save(update_fields=["attempts", "error"])
            return

        recipient.status = "sent"
        recipient.sent_at = timezone.now()
        recipient.attempts += 1
        recipient.save(update_fields=["status", "sent_at", "attempts"])
        with transaction.atomic():
            c = Campaign.objects.select_for_update().get(pk=campaign.pk)
            c.sent_count += 1
            c.save(update_fields=["sent_count"])

    def _maybe_complete(self, campaign):
        remaining = campaign.recipients.filter(status="pending").count()
        if remaining:
            return
        c = Campaign.objects.get(pk=campaign.pk)
        failed = c.recipients.filter(status="failed").count()
        sent = c.recipients.filter(status="sent").count()
        c.status = "failed" if (sent == 0 and failed > 0) else "sent"
        c.completed_at = timezone.now()
        c.save(update_fields=["status", "completed_at"])
```
Note: create the two empty `__init__.py` files under `management/` and `management/commands/`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test messaging.tests.test_send_engine -v 2`
Expected: PASS (all 4). If `test_failed_send_retries_then_fails` is slow due to connection timeout, that is acceptable; it must still end FAILED with 3 attempts.

- [ ] **Step 7: Document the cron entry**

Append to `README.md` a short "Bulk email" section:
```markdown
## Bulk email outbox

Queued campaigns are sent by a management command; run it every minute via cron:

    * * * * * cd /app/brandtechsolution && /app/.venv/bin/python manage.py process_email_outbox >> /var/log/outbox.log 2>&1

Tune `OUTBOX_BATCH_SIZE` (default 50) and cron frequency to stay under your
Gmail limits (~500/day free, ~2000/day Workspace). Example: batch 20 + a
per-5-minute cron ≈ safe for a free Gmail account.
```

- [ ] **Step 8: Commit**

```bash
git add brandtechsolution/messaging brandtechsolution/brandtechsolution/config.py brandtechsolution/brandtechsolution/settings.py README.md
git commit -m "feat(messaging): throttled outbox send command with retries and unsubscribe links"
```

---

### Task 12: Admin panel — extract sections into partials + static JS

**Files:**
- Create: `brandtechsolution/brand/static/brand/js/admin/core.js`
- Create: `brandtechsolution/brand/static/brand/js/admin/blogs.js`
- Create: `brandtechsolution/brand/static/brand/js/admin/projects.js`
- Create: `brandtechsolution/brand/templates/brand/admin/_blogs.html`
- Create: `brandtechsolution/brand/templates/brand/admin/_projects.html`
- Modify: `brandtechsolution/brand/templates/brand/admin_panel.html`
- Create: `brandtechsolution/messaging/tests/test_admin_panel_render.py`

**Interfaces:**
- Consumes: existing admin panel JS (`showSection`, `loadBlogs`, `loadProjects`, `addItem`, etc. from the current inline `<script>`).
- Produces: `core.js` exposing `showSection`, `showAddForm`, `hideAddForm`, `getCookie`, `CSRF_TOKEN`, `API_BASE` on `window`; `blogs.js`/`projects.js` their respective loaders. The panel template includes partials and loads these scripts with `defer`.

**Note:** This is a behavior-preserving refactor of the existing 585-line file. The deliverable is "panel still works exactly as before, now modular." Because the logic is JS, the automated test only asserts the template renders with the expected anchors; behavior is confirmed by manual verification.

- [ ] **Step 1: Write the render test**

Create `brandtechsolution/messaging/tests/test_admin_panel_render.py`:
```python
from django.contrib.auth.models import User
from django.test import TestCase


class AdminPanelRenderTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)

    def test_panel_renders_for_staff_with_sections(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for anchor in ['id="dashboard"', 'id="blogs"', 'id="projects"']:
            self.assertIn(anchor, html)
```
Run: `python manage.py test messaging.tests.test_admin_panel_render -v 2` → PASS already (baseline; confirms current behavior before refactor).

- [ ] **Step 2: Move blog/project section markup into partials**

Create `brandtechsolution/brand/templates/brand/admin/_blogs.html` containing the current `<div id="blogs" ...>...</div>` block (lines ~178-260 of `admin_panel.html`), verbatim.
Create `brandtechsolution/brand/templates/brand/admin/_projects.html` containing the current `<div id="projects" ...>...</div>` block (lines ~263-336), verbatim.

- [ ] **Step 3: Move JS into static modules**

Create `brandtechsolution/brand/static/brand/js/admin/core.js` with the shared helpers currently inline: `getCookie`, `CSRF_TOKEN`, `API_BASE`, sidebar toggle handlers, `showSection`, `showAddForm`, `hideAddForm`, `loadDashboard`, plus the `addItem`/`updateItem`/`deleteItem` CRUD helpers and the `DOMContentLoaded` init. (Copy verbatim from the current `<script>`.)
Create `brandtechsolution/brand/static/brand/js/admin/blogs.js` with `loadBlogs`, `editBlog`, and the `addBlogForm` submit binding.
Create `brandtechsolution/brand/static/brand/js/admin/projects.js` with `loadProjects`, `editProject`, and the `addProjectForm` submit binding.

- [ ] **Step 4: Rewire `admin_panel.html`**

In `admin_panel.html`:
- Replace the inline `<div id="blogs">` block with `{% include 'brand/admin/_blogs.html' %}`.
- Replace the inline `<div id="projects">` block with `{% include 'brand/admin/_projects.html' %}`.
- Delete the entire inline `<script>...</script>` block.
- Before `</body>`, add:
```html
<script src="{% static 'brand/js/admin/core.js' %}" defer></script>
<script src="{% static 'brand/js/admin/blogs.js' %}" defer></script>
<script src="{% static 'brand/js/admin/projects.js' %}" defer></script>
```

- [ ] **Step 5: Run the render test + manual verification**

Run: `python manage.py test messaging.tests.test_admin_panel_render -v 2` → PASS.
Manual: `runserver`, log in as staff, open `/admin-panel/`. Confirm Dashboard counts load, Blogs and Projects sections list/create/edit/delete exactly as before. (Use the verify skill.)

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/brand/templates/brand/admin_panel.html brandtechsolution/brand/templates/brand/admin brandtechsolution/brand/static/brand/js/admin brandtechsolution/messaging/tests/test_admin_panel_render.py
git commit -m "refactor(admin-panel): split sections into partials and static JS modules"
```

---

### Task 13: Admin panel — Inbox section

**Files:**
- Create: `brandtechsolution/brand/templates/brand/admin/_inbox.html`
- Create: `brandtechsolution/brand/static/brand/js/admin/inbox.js`
- Modify: `brandtechsolution/brand/templates/brand/admin_panel.html` (nav item, include, script)
- Modify: `brandtechsolution/messaging/tests/test_admin_panel_render.py` (assert inbox anchor)

**Interfaces:**
- Consumes: `/api/messaging/inquiries/` (list, PATCH status, DELETE).
- Produces: nav item calling `showSection('inbox', this)`; `inbox.js` exposing `loadInbox()`, `setInquiryStatus(id, status)`, `deleteInquiry(id)`; a section `<div id="inbox">`.

- [ ] **Step 1: Extend the render test**

In `test_admin_panel_render.py`, add `'id="inbox"'` to the asserted anchors list.
Run: `python manage.py test messaging.tests.test_admin_panel_render -v 2` → FAIL (anchor absent).

- [ ] **Step 2: Add the section partial**

Create `brandtechsolution/brand/templates/brand/admin/_inbox.html`:
```html
<div id="inbox" class="section hidden">
    <div class="mb-8">
        <h2 class="text-2xl font-bold text-white">Inbox</h2>
        <p class="text-gray-500 text-sm">Messages from the contact form</p>
    </div>
    <div id="inboxList" class="space-y-4"></div>
</div>
```

- [ ] **Step 3: Add the JS module**

Create `brandtechsolution/brand/static/brand/js/admin/inbox.js`:
```javascript
async function loadInbox() {
    try {
        const res = await fetch(`${API_BASE}/messaging/inquiries/`, { credentials: 'same-origin' });
        const items = await res.json();
        const container = document.getElementById('inboxList');
        if (!items.length) {
            container.innerHTML = `<div class="text-center py-10 text-gray-600">No messages yet.</div>`;
            return;
        }
        const badge = { new: 'text-brand-green bg-green-900/20', read: 'text-gray-300 bg-white/5', replied: 'text-brand-blue bg-blue-900/20', archived: 'text-gray-500 bg-white/5' };
        container.innerHTML = items.map(i => `
            <div class="bg-dark-card border border-dark-border p-5 rounded-lg">
                <div class="flex justify-between items-start gap-4">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-2">
                            <span class="text-xs font-bold px-2 py-1 rounded uppercase ${badge[i.status] || ''}">${i.status}</span>
                            <span class="text-gray-500 text-xs">${new Date(i.created_at).toLocaleString()}</span>
                        </div>
                        <h3 class="text-lg font-bold text-white">${i.name} <span class="text-sm text-gray-400 font-normal">&lt;${i.email}&gt;</span></h3>
                        ${i.phone ? `<p class="text-xs text-gray-500 mb-1">${i.phone}</p>` : ''}
                        <p class="text-gray-300 text-sm whitespace-pre-line mt-2">${i.message}</p>
                    </div>
                    <div class="flex flex-col gap-2">
                        <button onclick="setInquiryStatus(${i.id}, 'read')" class="p-2 text-gray-400 hover:bg-white/5 rounded" title="Mark read"><i class="fas fa-envelope-open"></i></button>
                        <button onclick="setInquiryStatus(${i.id}, 'replied')" class="p-2 text-brand-blue hover:bg-blue-900/30 rounded" title="Mark replied"><i class="fas fa-reply"></i></button>
                        <button onclick="setInquiryStatus(${i.id}, 'archived')" class="p-2 text-gray-400 hover:bg-white/5 rounded" title="Archive"><i class="fas fa-box-archive"></i></button>
                        <button onclick="deleteInquiry(${i.id})" class="p-2 text-red-400 hover:bg-red-900/30 rounded" title="Delete"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
            </div>`).join('');
    } catch (e) { console.error(e); }
}

async function setInquiryStatus(id, status) {
    await fetch(`${API_BASE}/messaging/inquiries/${id}/`, {
        method: 'PATCH', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ status }),
    });
    loadInbox();
}

async function deleteInquiry(id) {
    if (!confirm('Delete this message?')) return;
    await fetch(`${API_BASE}/messaging/inquiries/${id}/`, {
        method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    loadInbox();
}
```

- [ ] **Step 4: Wire nav + include + script + loader**

In `admin_panel.html`:
- Add a nav item in the sidebar (in the "Content" group or a new "Communications" group):
```html
<div class="pt-4 pb-2 px-4 text-xs font-semibold text-gray-600 uppercase tracking-wider">Communications</div>
<a href="#" onclick="showSection('inbox', this)" class="nav-item flex items-center px-4 py-3 text-sm font-medium rounded-lg text-gray-400 transition-colors">
    <i class="fas fa-inbox w-6 text-center mr-3"></i>Inbox
</a>
```
- Add `{% include 'brand/admin/_inbox.html' %}` in the main content area.
- Add `<script src="{% static 'brand/js/admin/inbox.js' %}" defer></script>` before `</body>`.
- In `core.js` `showSection`, add: `if (sectionName === 'inbox') loadInbox();`

- [ ] **Step 5: Run the render test + manual verify**

Run: `python manage.py test messaging.tests.test_admin_panel_render -v 2` → PASS.
Manual: open panel → Inbox lists submitted inquiries; status buttons and delete work (verify skill).

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/brand brandtechsolution/messaging/tests/test_admin_panel_render.py
git commit -m "feat(admin-panel): inbox section for contact inquiries"
```

---

### Task 14: Admin panel — Templates section

**Files:**
- Create: `brandtechsolution/brand/templates/brand/admin/_templates.html`
- Create: `brandtechsolution/brand/static/brand/js/admin/templates.js`
- Modify: `brandtechsolution/brand/templates/brand/admin_panel.html`
- Modify: `brandtechsolution/messaging/tests/test_admin_panel_render.py` (assert templates anchor)

**Interfaces:**
- Consumes: `/api/messaging/templates/` (CRUD).
- Produces: nav item `showSection('templates', this)`; `templates.js` exposing `loadTemplates()`, `saveTemplate(event)`, `editTemplate(id)`, `deleteTemplate(id)`; section `<div id="templates">`.

- [ ] **Step 1: Extend render test**

Add `'id="templates"'` to the anchors list in `test_admin_panel_render.py`.
Run test → FAIL.

- [ ] **Step 2: Add the partial**

Create `brandtechsolution/brand/templates/brand/admin/_templates.html`:
```html
<div id="templates" class="section hidden">
    <div class="flex justify-between items-center mb-8 gap-4">
        <div>
            <h2 class="text-2xl font-bold text-white">Email Templates</h2>
            <p class="text-gray-500 text-sm">Reusable email content</p>
        </div>
        <button onclick="showAddForm('template')" class="bg-brand-blue hover:bg-blue-600 text-white px-5 py-2.5 rounded-lg flex items-center transition-colors"><i class="fas fa-plus mr-2"></i>New Template</button>
    </div>
    <div id="templateForm" class="bg-dark-card border border-dark-border rounded-xl p-6 mb-8 hidden">
        <h3 class="text-lg font-bold text-white mb-6 border-b border-dark-border pb-4">New Template</h3>
        <form id="addTemplateForm" class="space-y-4">
            <input type="hidden" name="id">
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">Name</label>
                <input type="text" name="name" required class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
            </div>
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">Subject</label>
                <input type="text" name="subject" required class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
            </div>
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">HTML Body <span class="text-gray-600">(supports {{ name }} and {{ unsubscribe_url }})</span></label>
                <textarea name="body_html" rows="8" required class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white font-mono text-sm focus:outline-none focus:border-brand-blue"></textarea>
            </div>
            <div class="flex justify-end gap-3 pt-4 border-t border-dark-border">
                <button type="button" onclick="hideAddForm('template')" class="px-6 py-2.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5">Cancel</button>
                <button type="submit" class="bg-brand-blue hover:bg-blue-600 text-white px-6 py-2.5 rounded-lg font-medium">Save Template</button>
            </div>
        </form>
    </div>
    <div id="templatesList" class="space-y-4"></div>
</div>
```

- [ ] **Step 3: Add the JS module**

Create `brandtechsolution/brand/static/brand/js/admin/templates.js`:
```javascript
async function loadTemplates() {
    const res = await fetch(`${API_BASE}/messaging/templates/`, { credentials: 'same-origin' });
    const items = await res.json();
    const container = document.getElementById('templatesList');
    container.innerHTML = items.length ? items.map(t => `
        <div class="bg-dark-card border border-dark-border p-5 rounded-lg flex justify-between items-start gap-4">
            <div class="flex-1">
                <h3 class="text-lg font-bold text-white">${t.name}</h3>
                <p class="text-sm text-gray-400">${t.subject}</p>
            </div>
            <div class="flex gap-2">
                <button onclick="editTemplate(${t.id})" class="p-2 text-blue-400 hover:bg-blue-900/30 rounded"><i class="fas fa-edit"></i></button>
                <button onclick="deleteTemplate(${t.id})" class="p-2 text-red-400 hover:bg-red-900/30 rounded"><i class="fas fa-trash"></i></button>
            </div>
        </div>`).join('') : `<div class="text-center py-10 text-gray-600">No templates yet.</div>`;
}

async function saveTemplate(event) {
    event.preventDefault();
    const form = event.target;
    const id = form.id.value;
    const payload = { name: form.name.value, subject: form.subject.value, body_html: form.body_html.value };
    const url = id ? `${API_BASE}/messaging/templates/${id}/` : `${API_BASE}/messaging/templates/`;
    const method = id ? 'PUT' : 'POST';
    const res = await fetch(url, {
        method, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify(payload),
    });
    if (res.ok) { hideAddForm('template'); form.reset(); form.id.value = ''; loadTemplates(); }
    else { alert('Save failed'); }
}

async function editTemplate(id) {
    const t = await fetch(`${API_BASE}/messaging/templates/${id}/`, { credentials: 'same-origin' }).then(r => r.json());
    const form = document.getElementById('addTemplateForm');
    form.id.value = t.id; form.name.value = t.name; form.subject.value = t.subject; form.body_html.value = t.body_html;
    showAddForm('template');
}

async function deleteTemplate(id) {
    if (!confirm('Delete this template?')) return;
    await fetch(`${API_BASE}/messaging/templates/${id}/`, { method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN } });
    loadTemplates();
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addTemplateForm');
    if (form) form.addEventListener('submit', saveTemplate);
});
```

- [ ] **Step 4: Wire nav + include + script + loader**

In `admin_panel.html`: add nav item (`fas fa-file-lines`, `showSection('templates', this)`) under Communications, add `{% include 'brand/admin/_templates.html' %}`, add the `templates.js` script tag. In `core.js` `showSection`, add `if (sectionName === 'templates') loadTemplates();`.

- [ ] **Step 5: Run render test + manual verify**

Run: `python manage.py test messaging.tests.test_admin_panel_render -v 2` → PASS. Manual: create/edit/delete a template (verify skill).

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/brand brandtechsolution/messaging/tests/test_admin_panel_render.py
git commit -m "feat(admin-panel): email templates section"
```

---

### Task 15: Admin panel — Campaigns section (compose → audience → review → send)

**Files:**
- Create: `brandtechsolution/brand/templates/brand/admin/_campaigns.html`
- Create: `brandtechsolution/brand/static/brand/js/admin/campaigns.js`
- Modify: `brandtechsolution/brand/templates/brand/admin_panel.html`
- Modify: `brandtechsolution/messaging/tests/test_admin_panel_render.py` (assert campaigns anchor)

**Interfaces:**
- Consumes: `/api/messaging/campaigns/` (CRUD + `build_recipients` + `queue`), `/api/messaging/templates/`, `/api/messaging/extract-emails/`.
- Produces: nav item `showSection('campaigns', this)`; `campaigns.js` exposing `loadCampaigns()`, `createCampaign(event)`, `buildRecipients(id)`, `queueCampaign(id)`, `importEmails(event)`; section `<div id="campaigns">`.

- [ ] **Step 1: Extend render test**

Add `'id="campaigns"'` to the anchors list. Run → FAIL.

- [ ] **Step 2: Add the partial**

Create `brandtechsolution/brand/templates/brand/admin/_campaigns.html`:
```html
<div id="campaigns" class="section hidden">
    <div class="flex justify-between items-center mb-8 gap-4">
        <div>
            <h2 class="text-2xl font-bold text-white">Campaigns</h2>
            <p class="text-gray-500 text-sm">Compose and send bulk email</p>
        </div>
        <button onclick="showAddForm('campaign')" class="bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-2.5 rounded-lg flex items-center"><i class="fas fa-plus mr-2"></i>New Campaign</button>
    </div>

    <div id="campaignForm" class="bg-dark-card border border-dark-border rounded-xl p-6 mb-8 hidden">
        <h3 class="text-lg font-bold text-white mb-6 border-b border-dark-border pb-4">New Campaign</h3>
        <form id="addCampaignForm" class="space-y-4">
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">Campaign name (internal)</label>
                <input type="text" name="name" required class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
            </div>
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">Use a template (optional)</label>
                <select id="campaignTemplate" onchange="applyTemplate()" class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
                    <option value="">— none —</option>
                </select>
            </div>
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">Subject</label>
                <input type="text" name="subject" required class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
            </div>
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">HTML Body</label>
                <textarea name="body_html" rows="8" required class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white font-mono text-sm focus:outline-none focus:border-brand-blue"></textarea>
            </div>
            <div class="flex justify-end gap-3 pt-4 border-t border-dark-border">
                <button type="button" onclick="hideAddForm('campaign')" class="px-6 py-2.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5">Cancel</button>
                <button type="submit" class="bg-brand-green hover:bg-green-500 text-black px-6 py-2.5 rounded-lg font-semibold">Create Draft</button>
            </div>
        </form>
    </div>

    <div id="campaignsList" class="space-y-4"></div>
</div>
```

- [ ] **Step 3: Add the JS module**

Create `brandtechsolution/brand/static/brand/js/admin/campaigns.js`:
```javascript
let TEMPLATE_CACHE = [];

async function loadCampaigns() {
    // Populate template dropdown
    TEMPLATE_CACHE = await fetch(`${API_BASE}/messaging/templates/`, { credentials: 'same-origin' }).then(r => r.json());
    const sel = document.getElementById('campaignTemplate');
    if (sel) sel.innerHTML = `<option value="">— none —</option>` + TEMPLATE_CACHE.map(t => `<option value="${t.id}">${t.name}</option>`).join('');

    const items = await fetch(`${API_BASE}/messaging/campaigns/`, { credentials: 'same-origin' }).then(r => r.json());
    const container = document.getElementById('campaignsList');
    const statusColor = { draft: 'text-gray-400 bg-white/5', queued: 'text-brand-blue bg-blue-900/20', sending: 'text-yellow-400 bg-yellow-900/20', sent: 'text-brand-green bg-green-900/20', paused: 'text-orange-400 bg-orange-900/20', failed: 'text-red-400 bg-red-900/20' };
    container.innerHTML = items.length ? items.map(c => `
        <div class="bg-dark-card border border-dark-border p-5 rounded-lg">
            <div class="flex justify-between items-start gap-4">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2">
                        <span class="text-xs font-bold px-2 py-1 rounded uppercase ${statusColor[c.status] || ''}">${c.status}</span>
                    </div>
                    <h3 class="text-lg font-bold text-white">${c.name}</h3>
                    <p class="text-sm text-gray-400">${c.subject}</p>
                    <p class="text-xs text-gray-500 mt-2">${c.sent_count}/${c.total} sent${c.failed_count ? ` · ${c.failed_count} failed` : ''}</p>
                </div>
                <div class="flex flex-col gap-2 w-48">
                    ${c.status === 'draft' ? `
                        <label class="text-xs text-gray-400">Audience:</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="inquiries"> Inquiries</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="users"> Users</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="appointments"> Appointments</label>
                        <textarea id="manual-${c.id}" placeholder="paste emails, comma/space separated" class="bg-[#06090F] border border-dark-border rounded px-2 py-1 text-xs text-white" rows="2"></textarea>
                        <input type="file" id="import-${c.id}" onchange="importEmails(event)" data-c="${c.id}" class="text-xs text-gray-400" accept=".csv,.txt,.xlsx,.pdf,.docx">
                        <button onclick="buildRecipients(${c.id})" class="bg-dark-card border border-dark-border hover:border-brand-blue text-white text-xs px-3 py-1.5 rounded">Build recipients</button>
                        <button onclick="queueCampaign(${c.id})" class="bg-brand-green hover:bg-green-500 text-black text-xs font-semibold px-3 py-1.5 rounded">Queue send (${c.total})</button>
                    ` : ``}
                </div>
            </div>
        </div>`).join('') : `<div class="text-center py-10 text-gray-600">No campaigns yet.</div>`;
}

function applyTemplate() {
    const id = document.getElementById('campaignTemplate').value;
    const t = TEMPLATE_CACHE.find(x => String(x.id) === String(id));
    const form = document.getElementById('addCampaignForm');
    if (t) { form.subject.value = t.subject; form.body_html.value = t.body_html; }
}

async function createCampaign(event) {
    event.preventDefault();
    const form = event.target;
    const payload = { name: form.name.value, subject: form.subject.value, body_html: form.body_html.value };
    const res = await fetch(`${API_BASE}/messaging/campaigns/`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify(payload),
    });
    if (res.ok) { hideAddForm('campaign'); form.reset(); loadCampaigns(); } else { alert('Create failed'); }
}

function _manualEmails(id) {
    const el = document.getElementById(`manual-${id}`);
    return el ? el.value.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean) : [];
}

async function importEmails(event) {
    const input = event.target;
    const id = input.dataset.c;
    const fd = new FormData();
    fd.append('file', input.files[0]);
    const res = await fetch(`${API_BASE}/messaging/extract-emails/`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN }, body: fd,
    });
    if (res.ok) {
        const data = await res.json();
        const box = document.getElementById(`manual-${id}`);
        box.value = (box.value ? box.value + '\n' : '') + data.emails.join('\n');
        alert(`Imported ${data.count} email(s).`);
    } else { alert('Import failed'); }
}

async function buildRecipients(id) {
    const sources = Array.from(document.querySelectorAll(`.aud[data-c="${id}"]:checked`)).map(c => c.value);
    const res = await fetch(`${API_BASE}/messaging/campaigns/${id}/build_recipients/`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ sources, manual_emails: _manualEmails(id) }),
    });
    const data = await res.json();
    if (res.ok) { alert(`${data.count} recipient(s) ready.`); loadCampaigns(); } else { alert(data.detail || 'Failed'); }
}

async function queueCampaign(id) {
    if (!confirm('Queue this campaign for sending?')) return;
    const res = await fetch(`${API_BASE}/messaging/campaigns/${id}/queue/`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    const data = await res.json();
    if (res.ok) { alert('Queued! Sending will begin shortly.'); loadCampaigns(); } else { alert(data.detail || 'Failed'); }
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addCampaignForm');
    if (form) form.addEventListener('submit', createCampaign);
});
```

- [ ] **Step 4: Wire nav + include + script + loader**

In `admin_panel.html`: add nav item (`fas fa-paper-plane`, `showSection('campaigns', this)`) under Communications, add `{% include 'brand/admin/_campaigns.html' %}`, add the `campaigns.js` script tag. In `core.js` `showSection`, add `if (sectionName === 'campaigns') loadCampaigns();`.

- [ ] **Step 5: Run render test**

Run: `python manage.py test messaging.tests.test_admin_panel_render -v 2` → PASS.

- [ ] **Step 6: Full manual end-to-end verification (verify skill)**

1. `runserver`; log in as staff.
2. Templates → create a template with `{{ name }}` and an `{{ unsubscribe_url }}` link.
3. Campaigns → New Campaign, pick the template, Create Draft.
4. On the draft card: check "Inquiries", paste one of your own addresses, Build recipients → see count.
5. Queue send.
6. Run `python manage.py process_email_outbox` and confirm the email arrives; the card flips to `sent` with `n/n`.
7. Click the unsubscribe link in the received email → confirm a `Suppression` row is created and a re-send skips it.

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/brand brandtechsolution/messaging/tests/test_admin_panel_render.py
git commit -m "feat(admin-panel): campaigns section with audience build, import and queue"
```

---

### Task 16: Full-suite regression + final commit

**Files:** none (verification only)

- [ ] **Step 1: Run the entire messaging suite**

Run: `python manage.py test messaging -v 2`
Expected: all tests PASS.

- [ ] **Step 2: Run the whole project test suite (regression)**

Run: `python manage.py test -v 1`
Expected: no new failures introduced (brand/appointments tests still pass). If pgvector/test-DB setup fails in your environment, run `python manage.py test messaging brand -v 1` and note any pre-existing, unrelated failures.

- [ ] **Step 3: Check for missing migrations**

Run: `python manage.py makemigrations --check --dry-run`
Expected: "No changes detected". If not, create and commit the migration.

- [ ] **Step 4: Final commit (if anything pending)**

```bash
git add -A
git commit -m "test(messaging): full inbox + mailing suite green" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- New `messaging` app → Task 1. ✓
- `Inquiry` model + contact-form migration off Formspree → Tasks 1, 2. ✓
- `EmailTemplate` → Task 4. ✓
- `Campaign` / `CampaignRecipient` outbox → Task 6. ✓
- `Suppression` + signed unsubscribe → Task 5. ✓
- Audience resolution (inquiries/users/appointments/manual, dedup, suppression) → Task 7. ✓
- Document import (csv/txt/xlsx/pdf/docx) + endpoint → Tasks 8, 9. ✓
- Campaign build/queue API → Task 10. ✓
- Throttled outbox sender command + Gmail-limit docs + retries + placeholders → Task 11. ✓
- Admin-panel extraction + Inbox/Templates/Campaigns UI → Tasks 12–15. ✓
- Permissions (`IsAdminUser`), honeypot, upload guards → Tasks 2, 3, 9. ✓
- Testing per spec → each task's test steps + Task 16 regression. ✓

**Placeholder scan:** No TBD/TODO; every code step contains full code. UI tasks note the one intentional gap (JS behavior confirmed by manual verify, not unit test) with explicit render-test assertions.

**Type/name consistency:** `resolve_recipients`/`build_recipients` (Task 7) used identically in Tasks 10/11 context. `make_unsubscribe_token`/`read_unsubscribe_token` (Task 5) used in Task 11. `extract_emails_from_file`/`UnsupportedFileType` (Task 8) used in Task 9. `render_body`/`render_subject`/`html_to_text` (Task 11 Step 2) used in the command (Step 5). API basenames (`inquiries`, `templates`, `campaigns`) consistent between `api_urls.py` and JS fetch paths. Settings `OUTBOX_BATCH_SIZE`/`OUTBOX_MAX_ATTEMPTS`/`SITE_BASE_URL` defined in Task 11 Step 1 and consumed in Step 5.

**Scope:** One cohesive sub-project (inbox + mailing), 16 tasks, each independently testable. Deferred items (events, appointments, analytics, saved audiences, bounce webhooks) are explicitly out of scope per the spec.
