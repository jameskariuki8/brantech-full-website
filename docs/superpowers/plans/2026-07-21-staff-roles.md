# Staff Roles and Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the panel's single `is_staff` gate with named roles built on Django Groups, so access can be granted per capability and campaign sending can be reserved to administrators.

**Architecture:** A new `staff` app owns eleven custom permissions on a table-less sentinel model, plus one DRF permission factory and one view decorator. Every existing endpoint swaps its `IsAdminUser` / `is_staff` check for a capability check. The app also provides email invitations, an append-only audit log, and the panel UI for managing roles and people.

**Tech Stack:** Django 5.2.7, Django REST Framework, `django.core.signing` for invitation tokens, `django.core.mail.send_mail` for delivery, vanilla JS + Tailwind CDN for the panel.

## Global Constraints

- **Run all Django commands from `brandtechsolution/` using `.venv/bin/python`.** Plain `python`/`python3` lack Django. Example: `cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb`
- **`manage.py test` requires `--keepdb`.** Without it the runner hits an interactive prompt and aborts.
- **The full suite takes 5-6 minutes.** Use a command timeout of at least 400 seconds. Run only the app you touched during a task; run `messaging appointments brand.test_api_permissions staff` before the final commit of a task that touches enforcement.
- **`brand.tests` fails on a clean master with 7 failures and 17 errors.** This is the pre-existing baseline, not a regression. Do not fix it and do not treat it as your failure. Compare counts if in doubt.
- **This project sets no DRF global defaults.** There is no `DEFAULT_PERMISSION_CLASSES` and no `DEFAULT_PAGINATION_CLASS`. Every viewset must set `permission_classes` explicitly and every list endpoint must set `pagination_class` explicitly.
- **Capability codenames are checked as `staff.<codename>`** — for example `user.has_perm("staff.send_campaigns")`.
- **Superusers bypass every capability check.** `has_perm()` returns `True` for them unconditionally. Never add code that would deny a superuser.
- **Every value rendered into the admin panel must pass through `escapeHtml()`** (defined in `brand/static/brand/js/admin/core.js`).
- **Never build a JavaScript string inside an HTML attribute.** Browsers entity-decode attribute values before compiling handlers, so `escapeHtml` alone is not sufficient there. Use `data-` attributes plus a delegated listener.
- **Do not modify `messaging/management/commands/process_email_outbox.py`.** No task in this plan needs to.
- **No test may perform real network access**, including DNS and SMTP. Django's test runner uses the locmem email backend automatically; do not override it.
- **Blog draft state:** the migration adding `BlogPost.status` must backfill every existing row to `published`. A plain default empties the live blog.

---

## File Structure

**New app `brandtechsolution/staff/`:**

| File | Responsibility |
|---|---|
| `capabilities.py` | The registry. Single source of truth for the eleven capabilities and their UI grouping. |
| `models.py` | `StaffCapability` (sentinel, owns the permissions), `StaffInvitation`, `AuditEntry`. |
| `permissions.py` | `has_capability(codename)` — DRF permission class factory. |
| `decorators.py` | `capability_required(codename)` — for plain Django views. |
| `audit.py` | `record(...)` — writes one `AuditEntry`. |
| `tokens.py` | Invitation token sign/read. |
| `emails.py` | Invitation delivery. |
| `serializers.py` | Group, staff user, invitation, audit serializers. |
| `api.py` | Roles, people, invitations, audit, capability-list endpoints. |
| `views.py` | The invitation acceptance page. |
| `api_urls.py`, `urls.py` | Routing. |

**Modified:**

- `brandtechsolution/brandtechsolution/settings.py` — add `staff` to `INSTALLED_APPS`.
- `brandtechsolution/brandtechsolution/urls.py` — mount `staff` routes.
- `brandtechsolution/messaging/api.py` — swap `IsAdminUser` for capabilities.
- `brandtechsolution/brand/api_views.py` — swap `staff_required` for capabilities.
- `brandtechsolution/brand/api.py`, `brand/api_urls.py` — delete duplicate routes.
- `brandtechsolution/brand/models.py`, `brand/views.py` — blog draft state.
- `brandtechsolution/appointments/views.py` — swap staff checks for capabilities.
- `brandtechsolution/brand/templates/brand/admin_panel.html` — nav gating, new section.
- `brandtechsolution/brand/static/brand/js/admin/campaigns.js` — send-button state.

---

## Task 1: The `staff` app, capability registry and sentinel model

**Files:**
- Create: `brandtechsolution/staff/__init__.py`, `staff/apps.py`, `staff/capabilities.py`, `staff/models.py`, `staff/migrations/__init__.py`
- Modify: `brandtechsolution/brandtechsolution/settings.py`
- Test: `brandtechsolution/staff/tests/__init__.py`, `staff/tests/test_capabilities.py`

**Interfaces:**
- Produces: `staff.capabilities.CAPABILITY_GROUPS` (list of `(group_label, [(codename, label), ...])`), `staff.capabilities.ALL_CAPABILITIES` (flat list of `(codename, label)`), `staff.capabilities.CODENAMES` (list of str), `staff.capabilities.permission_tuples()`.

- [ ] **Step 1: Create the app skeleton**

```bash
cd brandtechsolution
mkdir -p staff/migrations staff/tests
touch staff/__init__.py staff/migrations/__init__.py staff/tests/__init__.py
```

Create `staff/apps.py`:

```python
from django.apps import AppConfig


class StaffConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "staff"
```

- [ ] **Step 2: Write the registry**

Create `staff/capabilities.py`:

```python
"""The panel's capability list.

This is the single source of truth. It feeds StaffCapability.Meta.permissions,
the API's capability-list endpoint and the UI checkboxes, so those three cannot
drift apart.
"""

CAPABILITY_GROUPS = [
    (
        "Content",
        [
            ("manage_blog", "Manage blog posts"),
            ("publish_blog", "Publish blog posts"),
            ("manage_projects", "Manage projects"),
            ("manage_appointments", "Manage appointments"),
        ],
    ),
    (
        "Communications",
        [
            ("view_inbox", "View inbox"),
            ("handle_inquiries", "Reply to and archive inquiries"),
            ("manage_templates", "Manage email templates"),
            ("manage_campaigns", "Create and edit campaigns"),
            ("manage_recipients", "Manage campaign recipients"),
            ("send_campaigns", "Send campaigns"),
        ],
    ),
    (
        "Administration",
        [
            ("manage_staff", "Manage staff and roles"),
        ],
    ),
]

ALL_CAPABILITIES = [
    pair for _label, pairs in CAPABILITY_GROUPS for pair in pairs
]

CODENAMES = [codename for codename, _label in ALL_CAPABILITIES]


def permission_tuples():
    """The list Django's Meta.permissions expects."""
    return list(ALL_CAPABILITIES)
```

- [ ] **Step 3: Write the failing test**

Create `staff/tests/test_capabilities.py`:

```python
from django.contrib.auth.models import Permission, User
from django.test import TestCase

from staff.capabilities import ALL_CAPABILITIES, CODENAMES


class CapabilityRegistryTest(TestCase):
    def test_registry_has_eleven_capabilities(self):
        self.assertEqual(len(ALL_CAPABILITIES), 11)

    def test_codenames_are_unique(self):
        self.assertEqual(len(CODENAMES), len(set(CODENAMES)))


class CapabilityPermissionsExistTest(TestCase):
    """post_migrate must have created one auth_permission row per capability."""

    def test_every_capability_has_a_permission_row(self):
        for codename in CODENAMES:
            with self.subTest(codename=codename):
                self.assertTrue(
                    Permission.objects.filter(
                        codename=codename, content_type__app_label="staff"
                    ).exists(),
                    f"No permission row for staff.{codename}",
                )

    def test_no_crud_permissions_were_generated(self):
        """default_permissions = () must suppress add/change/delete/view."""
        generated = Permission.objects.filter(
            content_type__app_label="staff"
        ).values_list("codename", flat=True)
        self.assertEqual(sorted(generated), sorted(CODENAMES))

    def test_permissions_are_checkable_on_a_user(self):
        user = User.objects.create_user("u", password="p", is_staff=True)
        user.user_permissions.add(
            Permission.objects.get(
                codename="send_campaigns", content_type__app_label="staff"
            )
        )
        user = User.objects.get(pk=user.pk)  # drop the permission cache
        self.assertTrue(user.has_perm("staff.send_campaigns"))
        self.assertFalse(user.has_perm("staff.manage_staff"))

    def test_superuser_has_every_capability(self):
        root = User.objects.create_superuser("root", password="p")
        for codename in CODENAMES:
            with self.subTest(codename=codename):
                self.assertTrue(root.has_perm(f"staff.{codename}"))
```

- [ ] **Step 4: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: FAIL — `ModuleNotFoundError: No module named 'staff'` or `No installed app with label 'staff'`.

- [ ] **Step 5: Write the sentinel model**

Create `staff/models.py`:

```python
from django.db import models

from .capabilities import permission_tuples


class StaffCapability(models.Model):
    """Owns the panel's permissions. Has no table and never holds rows.

    Django requires a permission to hang off a model. Attaching these to
    BlogPost, Campaign and friends would bury them among the auto-generated
    CRUD permissions, so they live here instead. managed = False means no
    table is created; default_permissions = () suppresses add/change/delete/
    view. post_migrate still creates the auth_permission rows, so these behave
    as ordinary Django permissions.
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = permission_tuples()
```

- [ ] **Step 6: Register the app**

In `brandtechsolution/brandtechsolution/settings.py`, add `'staff',` to the end of `INSTALLED_APPS`:

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
    'staff',
]
```

- [ ] **Step 7: Generate the migration**

```bash
cd brandtechsolution && .venv/bin/python manage.py makemigrations staff
```

Expected: `Create model StaffCapability`. Because the model is unmanaged this creates model state only — no table.

- [ ] **Step 8: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: 5 tests, OK.

If `test_no_crud_permissions_were_generated` fails with stale codenames present, the test database predates `default_permissions = ()`. Re-run once without `--keepdb` to rebuild it, then resume using `--keepdb`.

- [ ] **Step 9: Commit**

```bash
git add brandtechsolution/staff brandtechsolution/brandtechsolution/settings.py
git commit -m "feat(staff): add capability registry and sentinel permission model"
```

---

## Task 2: Preset roles

**Files:**
- Create: `brandtechsolution/staff/migrations/0002_preset_roles.py`
- Test: `brandtechsolution/staff/tests/test_preset_roles.py`

**Interfaces:**
- Consumes: `staff.capabilities.CODENAMES` from Task 1.
- Produces: four `auth.Group` rows named `Editor`, `Marketing`, `Support`, `Administrator`.

- [ ] **Step 1: Write the failing test**

Create `staff/tests/test_preset_roles.py`:

```python
from django.contrib.auth.models import Group
from django.test import TestCase

from staff.capabilities import CODENAMES

EXPECTED = {
    "Editor": {"manage_blog", "publish_blog", "manage_projects"},
    "Marketing": {"manage_templates", "manage_campaigns", "manage_recipients"},
    "Support": {"view_inbox", "handle_inquiries", "manage_appointments"},
    "Administrator": set(CODENAMES),
}


class PresetRoleTest(TestCase):
    def test_all_four_presets_exist(self):
        self.assertEqual(
            sorted(Group.objects.values_list("name", flat=True)),
            sorted(EXPECTED),
        )

    def test_each_preset_has_the_expected_capabilities(self):
        for name, codenames in EXPECTED.items():
            with self.subTest(role=name):
                group = Group.objects.get(name=name)
                actual = set(
                    group.permissions.values_list("codename", flat=True)
                )
                self.assertEqual(actual, codenames)

    def test_marketing_cannot_send_campaigns(self):
        """Sending is reserved to administrators by default."""
        marketing = Group.objects.get(name="Marketing")
        self.assertNotIn(
            "send_campaigns",
            marketing.permissions.values_list("codename", flat=True),
        )

    def test_administrator_can_send_campaigns(self):
        admin = Group.objects.get(name="Administrator")
        self.assertIn(
            "send_campaigns",
            admin.permissions.values_list("codename", flat=True),
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff.tests.test_preset_roles --keepdb
```

Expected: FAIL — `[] != ['Administrator', 'Editor', 'Marketing', 'Support']`.

- [ ] **Step 3: Write the data migration**

Create `staff/migrations/0002_preset_roles.py`:

```python
from django.db import migrations

PRESETS = {
    "Editor": ["manage_blog", "publish_blog", "manage_projects"],
    "Marketing": ["manage_templates", "manage_campaigns", "manage_recipients"],
    "Support": ["view_inbox", "handle_inquiries", "manage_appointments"],
    "Administrator": [
        "manage_blog",
        "publish_blog",
        "manage_projects",
        "manage_appointments",
        "view_inbox",
        "handle_inquiries",
        "manage_templates",
        "manage_campaigns",
        "manage_recipients",
        "send_campaigns",
        "manage_staff",
    ],
}


def create_presets(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    for name, codenames in PRESETS.items():
        group, _ = Group.objects.get_or_create(name=name)
        perms = Permission.objects.filter(
            codename__in=codenames, content_type__app_label="staff"
        )
        group.permissions.set(perms)


def remove_presets(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=PRESETS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0001_initial"),
        # Permissions are created by a post_migrate signal on contenttypes/auth,
        # so this migration must not run before those apps are fully migrated.
        ("auth", "__first__"),
        ("contenttypes", "__first__"),
    ]

    operations = [
        migrations.RunPython(create_presets, remove_presets),
    ]
```

**Note on ordering:** Django creates permission rows in a `post_migrate` handler, which runs *after* all migrations in a run. On a completely fresh database the permissions therefore do not exist while this migration executes, and `Permission.objects.filter(...)` returns nothing — leaving the presets empty.

Guard against that by creating the permissions explicitly first. Replace the body of `create_presets` with:

```python
def create_presets(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    from staff.capabilities import ALL_CAPABILITIES

    content_type, _ = ContentType.objects.get_or_create(
        app_label="staff", model="staffcapability"
    )
    for codename, label in ALL_CAPABILITIES:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=content_type,
            defaults={"name": label},
        )

    for name, codenames in PRESETS.items():
        group, _ = Group.objects.get_or_create(name=name)
        perms = Permission.objects.filter(
            codename__in=codenames, content_type=content_type
        )
        group.permissions.set(perms)
```

`get_or_create` makes this idempotent and harmless when `post_migrate` later creates the same rows.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: 9 tests, OK.

- [ ] **Step 5: Verify it works on a fresh database**

This is the case the ordering note above guards against, so prove it:

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff.tests.test_preset_roles
```

Note the deliberate absence of `--keepdb` — this builds the test database from scratch. Answer `yes` if prompted to delete an existing test database.

Expected: 4 tests, OK. If the capability sets come back empty, the explicit permission creation in Step 3 is missing or misplaced.

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/staff
git commit -m "feat(staff): ship four preset roles as a data migration"
```

---

## Task 3: Enforcement primitives

**Files:**
- Create: `brandtechsolution/staff/permissions.py`, `staff/decorators.py`
- Test: `brandtechsolution/staff/tests/test_enforcement.py`

**Interfaces:**
- Produces:
  - `staff.permissions.has_capability(codename: str) -> type[BasePermission]` — DRF permission class factory.
  - `staff.decorators.capability_required(codename: str)` — view decorator. Redirects anonymous users to `/login/`, raises `PermissionDenied` (403) for a signed-in user lacking the capability.

- [ ] **Step 1: Write the failing test**

Create `staff/tests/test_enforcement.py`:

```python
from django.contrib.auth.models import Permission, User
from django.test import RequestFactory, TestCase
from rest_framework.test import APIRequestFactory

from staff.decorators import capability_required
from staff.permissions import has_capability


def grant(user, codename):
    user.user_permissions.add(
        Permission.objects.get(
            codename=codename, content_type__app_label="staff"
        )
    )
    return User.objects.get(pk=user.pk)  # drop the permission cache


class HasCapabilityTest(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = has_capability("send_campaigns")()

    def _check(self, user):
        request = self.factory.get("/")
        request.user = user
        return self.permission.has_permission(request, None)

    def test_anonymous_is_denied(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(self._check(AnonymousUser()))

    def test_non_staff_with_the_permission_is_denied(self):
        """is_staff is a floor: the panel is not for ordinary accounts."""
        user = grant(User.objects.create_user("u", password="p"), "send_campaigns")
        self.assertFalse(self._check(user))

    def test_staff_without_the_capability_is_denied(self):
        user = User.objects.create_user("u", password="p", is_staff=True)
        self.assertFalse(self._check(user))

    def test_staff_with_the_capability_is_allowed(self):
        user = grant(
            User.objects.create_user("u", password="p", is_staff=True),
            "send_campaigns",
        )
        self.assertTrue(self._check(user))

    def test_staff_with_a_different_capability_is_denied(self):
        user = grant(
            User.objects.create_user("u", password="p", is_staff=True),
            "manage_blog",
        )
        self.assertFalse(self._check(user))

    def test_superuser_is_allowed(self):
        self.assertTrue(self._check(User.objects.create_superuser("r", password="p")))


class CapabilityRequiredTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        @capability_required("manage_appointments")
        def view(request):
            from django.http import HttpResponse

            return HttpResponse("ok")

        self.view = view

    def test_anonymous_is_redirected_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/appointments/")
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_staff_without_the_capability_gets_403(self):
        from django.core.exceptions import PermissionDenied

        request = self.factory.get("/appointments/")
        request.user = User.objects.create_user("u", password="p", is_staff=True)
        with self.assertRaises(PermissionDenied):
            self.view(request)

    def test_staff_with_the_capability_passes(self):
        request = self.factory.get("/appointments/")
        request.user = grant(
            User.objects.create_user("u", password="p", is_staff=True),
            "manage_appointments",
        )
        self.assertEqual(self.view(request).status_code, 200)

    def test_superuser_passes(self):
        request = self.factory.get("/appointments/")
        request.user = User.objects.create_superuser("r", password="p")
        self.assertEqual(self.view(request).status_code, 200)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff.tests.test_enforcement --keepdb
```

Expected: FAIL — `ModuleNotFoundError: No module named 'staff.permissions'`.

- [ ] **Step 3: Write the DRF permission factory**

Create `staff/permissions.py`:

```python
from rest_framework.permissions import BasePermission


def has_capability(codename):
    """Build a DRF permission class requiring one named capability.

    Usage:
        permission_classes = [has_capability("manage_campaigns")]

    is_staff is required in addition to the capability: the panel is not for
    ordinary signed-up accounts, and /signup/ is public. Superusers pass
    because has_perm() returns True for them unconditionally.
    """

    class _HasCapability(BasePermission):
        message = f"This action requires the '{codename}' capability."

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated and user.is_staff):
                return False
            return user.has_perm(f"staff.{codename}")

    _HasCapability.__name__ = f"HasCapability_{codename}"
    return _HasCapability
```

- [ ] **Step 4: Write the view decorator**

Create `staff/decorators.py`:

```python
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def capability_required(codename, login_url="/login/"):
    """Require a named capability on a plain Django view.

    Anonymous users are redirected to the login page, matching the existing
    behaviour of the panel's login_required gates. A signed-in user who lacks
    the capability gets a 403 rather than a redirect, because bouncing an
    already-authenticated user to a login form is a dead end.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path(), login_url)
            if not (user.is_staff and user.has_perm(f"staff.{codename}")):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: 19 tests, OK.

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/staff
git commit -m "feat(staff): add capability permission class and view decorator"
```

---

## Task 4: Enforce capabilities across the messaging API

**Files:**
- Modify: `brandtechsolution/messaging/api.py`
- Test: `brandtechsolution/messaging/tests/test_capability_enforcement.py`

**Interfaces:**
- Consumes: `staff.permissions.has_capability` from Task 3.

**Capability mapping for this task:**

| Viewset / action | Capability |
|---|---|
| `InquiryViewSet` safe methods (GET/HEAD/OPTIONS) | `view_inbox` |
| `InquiryViewSet` unsafe methods | `handle_inquiries` |
| `EmailTemplateViewSet` (all) | `manage_templates` |
| `CampaignViewSet` default | `manage_campaigns` |
| `CampaignViewSet.build_recipients` | `manage_recipients` |
| `CampaignViewSet.queue` / `pause` / `resume` | `send_campaigns` |
| `CampaignRecipientViewSet` (all) | `manage_recipients` |
| `extract_emails` | `manage_campaigns` |
| `placeholders` | `manage_campaigns` |
| `preview` | `manage_campaigns` |

`queue` is the action that commits a campaign to being sent, so it carries `send_campaigns` along with `pause` and `resume`.

- [ ] **Step 1: Write the failing test**

Create `messaging/tests/test_capability_enforcement.py`:

```python
from django.contrib.auth.models import Permission, User
from django.test import TestCase

from messaging.models import Campaign, EmailTemplate, Inquiry


def staff_with(*codenames):
    user = User.objects.create_user(
        f"u{abs(hash(codenames)) % 100000}", password="p", is_staff=True
    )
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class InquiryCapabilityTest(TestCase):
    def setUp(self):
        Inquiry.objects.create(name="n", email="a@b.com", message="m")

    def test_view_inbox_allows_reading(self):
        self.client.force_login(staff_with("view_inbox"))
        self.assertEqual(self.client.get("/api/messaging/inquiries/").status_code, 200)

    def test_no_capability_cannot_read(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/messaging/inquiries/").status_code, 403)

    def test_view_inbox_alone_cannot_write(self):
        inquiry = Inquiry.objects.first()
        self.client.force_login(staff_with("view_inbox"))
        resp = self.client.patch(
            f"/api/messaging/inquiries/{inquiry.pk}/",
            {"status": "archived"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_handle_inquiries_can_write(self):
        inquiry = Inquiry.objects.first()
        self.client.force_login(staff_with("view_inbox", "handle_inquiries"))
        resp = self.client.patch(
            f"/api/messaging/inquiries/{inquiry.pk}/",
            {"status": "archived"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)


class TemplateCapabilityTest(TestCase):
    def test_requires_manage_templates(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/messaging/templates/").status_code, 403)

    def test_manage_templates_allows_access(self):
        self.client.force_login(staff_with("manage_templates"))
        self.assertEqual(self.client.get("/api/messaging/templates/").status_code, 200)


class CampaignSendCapabilityTest(TestCase):
    """The central case: building a campaign is separate from sending it."""

    def setUp(self):
        self.campaign = Campaign.objects.create(
            name="c", subject="s", body_source="<p>b</p>", body_html="<p>b</p>",
            status="draft", total=5,
        )

    def test_manage_campaigns_can_edit_but_not_queue(self):
        self.client.force_login(staff_with("manage_campaigns"))
        self.assertEqual(
            self.client.get(f"/api/messaging/campaigns/{self.campaign.pk}/").status_code,
            200,
        )
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/queue/")
        self.assertEqual(resp.status_code, 403)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, "draft")

    def test_send_campaigns_can_queue(self):
        self.client.force_login(staff_with("manage_campaigns", "send_campaigns"))
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/queue/")
        self.assertEqual(resp.status_code, 200)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, "queued")

    def test_pause_requires_send_campaigns(self):
        self.campaign.status = "queued"
        self.campaign.save(update_fields=["status"])
        self.client.force_login(staff_with("manage_campaigns"))
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/pause/")
        self.assertEqual(resp.status_code, 403)

    def test_resume_requires_send_campaigns(self):
        self.campaign.status = "paused"
        self.campaign.save(update_fields=["status"])
        self.client.force_login(staff_with("manage_campaigns"))
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/resume/")
        self.assertEqual(resp.status_code, 403)

    def test_build_recipients_requires_manage_recipients(self):
        self.client.force_login(staff_with("manage_campaigns"))
        resp = self.client.post(
            f"/api/messaging/campaigns/{self.campaign.pk}/build_recipients/",
            {"sources": [], "manual_emails": []},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_superuser_can_do_everything(self):
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        resp = self.client.post(f"/api/messaging/campaigns/{self.campaign.pk}/queue/")
        self.assertEqual(resp.status_code, 200)


class RecipientCapabilityTest(TestCase):
    def test_requires_manage_recipients(self):
        campaign = Campaign.objects.create(
            name="c", subject="s", body_source="<p>b</p>", body_html="<p>b</p>",
        )
        self.client.force_login(staff_with("manage_campaigns"))
        resp = self.client.get(f"/api/messaging/recipients/?campaign={campaign.pk}")
        self.assertEqual(resp.status_code, 403)


class HelperEndpointCapabilityTest(TestCase):
    def test_placeholders_requires_manage_campaigns(self):
        self.client.force_login(staff_with())
        self.assertEqual(
            self.client.get("/api/messaging/placeholders/").status_code, 403
        )

    def test_placeholders_allowed_with_manage_campaigns(self):
        self.client.force_login(staff_with("manage_campaigns"))
        self.assertEqual(
            self.client.get("/api/messaging/placeholders/").status_code, 200
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test messaging.tests.test_capability_enforcement --keepdb
```

Expected: FAIL — endpoints return 200 where 403 is asserted, because `IsAdminUser` still admits any staff account.

- [ ] **Step 3: Replace the permission classes**

In `messaging/api.py`, replace the `IsAdminUser` import:

```python
from staff.permissions import has_capability
```

Delete `from rest_framework.permissions import IsAdminUser` if nothing else uses it.

`InquiryViewSet` needs different capabilities for reads and writes, so it overrides `get_permissions`:

```python
class InquiryViewSet(viewsets.ModelViewSet):
    queryset = Inquiry.objects.all()
    serializer_class = InquirySerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [has_capability("view_inbox")()]
        return [has_capability("handle_inquiries")()]
```

Add `from rest_framework import permissions` to the imports.

`EmailTemplateViewSet`:

```python
    permission_classes = [has_capability("manage_templates")]
```

`CampaignViewSet` needs a per-action map, so it also overrides `get_permissions`:

```python
class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer

    # Sending is the one irreversible, externally visible action, so it is
    # gated separately from ordinary campaign editing.
    ACTION_CAPABILITIES = {
        "build_recipients": "manage_recipients",
        "queue": "send_campaigns",
        "pause": "send_campaigns",
        "resume": "send_campaigns",
    }

    def get_permissions(self):
        capability = self.ACTION_CAPABILITIES.get(self.action, "manage_campaigns")
        return [has_capability(capability)()]
```

`CampaignRecipientViewSet`:

```python
    permission_classes = [has_capability("manage_recipients")]
```

The three function-based views change their decorator:

```python
@api_view(["POST"])
@permission_classes([has_capability("manage_campaigns")])
@parser_classes(...)          # unchanged
def extract_emails(request):
```

Apply the same to `placeholders` and `preview`. Note `permission_classes` here is DRF's decorator, imported at `messaging/api.py:366`; do not confuse it with the viewset attribute.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd brandtechsolution && .venv/bin/python manage.py test messaging.tests.test_capability_enforcement --keepdb
```

Expected: 15 tests, OK.

- [ ] **Step 5: Run the whole messaging suite for regressions**

```bash
cd brandtechsolution && .venv/bin/python manage.py test messaging --keepdb
```

Expected: OK. The pre-existing messaging tests sign in with `is_staff=True` accounts that now hold no capabilities, so **many will fail with 403**. That is a real consequence of this change, not a flaw in the tests: fix them by granting the capability each test needs.

Add this helper to `messaging/tests/__init__.py` and use it from the failing tests:

```python
from django.contrib.auth.models import Permission


def grant_all_capabilities(user):
    """Give a test's staff user every capability.

    Most messaging tests predate roles and only care that the caller is
    authorised at all. Rather than thread a capability list through each of
    them, they grant everything; the tests that specifically exercise
    capability boundaries live in test_capability_enforcement.py.
    """
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="staff")
    )
    user.refresh_from_db()
    return user
```

In each failing test's `setUp`, wrap the existing user creation:

```python
self.staff = grant_all_capabilities(
    User.objects.create_user("staff", password="p", is_staff=True)
)
```

`user.refresh_from_db()` does not clear Django's permission cache on its own. If a test still sees 403 after granting, re-fetch the user with `User.objects.get(pk=user.pk)` instead.

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/messaging
git commit -m "feat(messaging): gate endpoints on capabilities, reserving send"
```

---

## Task 5: Enforce capabilities on the brand content APIs and delete the duplicate routes

**Files:**
- Modify: `brandtechsolution/brand/api_views.py`, `brand/api.py`, `brand/api_urls.py`
- Test: `brandtechsolution/brand/test_api_permissions.py`

**Interfaces:**
- Consumes: `staff.decorators.capability_required` is *not* used here; these are JSON views that must return 403 rather than raise, so they keep the existing early-return style with a new helper.
- Produces: `brand.api_views.capability_required_json(request, codename) -> JsonResponse | None`.

**Context:** `/api/posts/` and `/api/projects/` are implemented twice — function views in `api_views.py` and router viewsets in `api.py`. The function views shadow the router only on `<int:pk>` paths, which left `/api/posts.json` reaching an unprotected viewset. This task keeps the function views (they handle the multipart uploads the panel sends) and deletes the router viewsets. `/api/events/` has no consumer anywhere and is deleted outright.

- [ ] **Step 1: Confirm nothing depends on the routes being deleted**

```bash
cd brandtechsolution
grep -rn "api/events\|posts.json\|projects.json\|increment_view\|blog-posts" \
  --include="*.js" --include="*.html" --include="*.py" \
  brand messaging appointments ai_workflows | grep -v "\.venv" | grep -v test_
```

Expected: no matches for `api/events`, `posts.json`, `projects.json` or `increment_view`. If any appear, stop and report before deleting.

- [ ] **Step 2: Write the failing test**

Append to `brand/test_api_permissions.py`:

```python
from django.contrib.auth.models import Permission


def staff_with(*codenames):
    user = User.objects.create_user("cap", password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class ContentCapabilityTest(TestCase):
    def setUp(self):
        self.post = BlogPost.objects.create(
            title="t", content="c", excerpt="e", category="cat"
        )

    def test_staff_without_manage_blog_cannot_create(self):
        self.client.force_login(staff_with())
        resp = self.client.post(
            "/api/posts/",
            {"title": "x", "content": "c", "excerpt": "e", "category": "cat"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_manage_blog_can_create(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            "/api/posts/",
            {"title": "x", "content": "c", "excerpt": "e", "category": "cat"},
        )
        self.assertEqual(resp.status_code, 201)

    def test_manage_blog_does_not_grant_project_access(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            "/api/projects/",
            {"title": "x", "description": "d", "short_description": "s"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_manage_projects_can_create_projects(self):
        self.client.force_login(staff_with("manage_projects"))
        resp = self.client.post(
            "/api/projects/",
            {"title": "x", "description": "d", "short_description": "s"},
        )
        self.assertEqual(resp.status_code, 201)

    def test_reads_remain_public(self):
        self.assertEqual(self.client.get("/api/posts/").status_code, 200)
        self.assertEqual(self.client.get("/api/projects/").status_code, 200)


class DeletedRouteTest(TestCase):
    """The duplicate router routes and the unused events route are gone."""

    def test_events_route_is_gone(self):
        self.assertEqual(self.client.get("/api/events/").status_code, 404)

    def test_posts_format_suffix_route_is_gone(self):
        self.assertEqual(self.client.get("/api/posts.json").status_code, 404)

    def test_projects_format_suffix_route_is_gone(self):
        self.assertEqual(self.client.get("/api/projects.json").status_code, 404)
```

Delete the `RouterBypassTest` class from this file — those routes no longer exist, so `DeletedRouteTest` replaces it.

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test brand.test_api_permissions --keepdb
```

Expected: FAIL — `403 != 201` on the capability tests and `404 != 200` on the deleted-route tests.

- [ ] **Step 4: Add the capability helper and apply it**

In `brand/api_views.py`, replace the `staff_required` helper added by commit `49d31d8`:

```python
def capability_required_json(request, codename):
    """Return an error response unless the request carries a capability.

    Returns None when the request may proceed. These are plain JSON views
    rather than DRF, so they return a response instead of raising.
    """
    user = request.user
    if not user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    if not (user.is_staff and user.has_perm(f'staff.{codename}')):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    return None
```

Replace each of the six call sites. In `post_list` and `post_detail`:

```python
        denied = capability_required_json(request, 'manage_blog')
        if denied:
            return denied
```

In `project_list` and `project_detail`:

```python
        denied = capability_required_json(request, 'manage_projects')
        if denied:
            return denied
```

There are three call sites in each pair of views (POST on the list view; POST/PUT and DELETE on the detail view). Delete the now-unused `staff_required` function.

- [ ] **Step 5: Delete the duplicate viewsets and routes**

Replace the whole of `brand/api_urls.py` with:

```python
from django.urls import path

from . import api

urlpatterns = [
    path('blog-posts/', api.blog_posts_api, name='blog-posts'),
]
```

In `brand/api.py`, delete the `BlogPostViewSet`, `ProjectViewSet` and `EventViewSet` classes entirely, along with the now-unused imports (`viewsets`, `action`, `get_object_or_404`, `StaffWriteOrReadOnly`, and the serializer imports that only those classes used). Keep `blog_posts_api` and whatever it needs.

Delete `brand/permissions.py` — `StaffWriteOrReadOnly` existed only for those viewsets.

Remove the now-dangling `StaffWriteOrReadOnly` import from `brand/test_api_permissions.py` if present.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test brand.test_api_permissions --keepdb
```

Expected: OK.

- [ ] **Step 7: Check the baseline did not move**

```bash
cd brandtechsolution && .venv/bin/python manage.py test brand.tests --keepdb 2>&1 | tail -3
```

Expected: `FAILED (failures=7, errors=17)` — the documented pre-existing baseline. Any other number means this task broke something; investigate before committing.

- [ ] **Step 8: Commit**

```bash
git add brandtechsolution/brand
git commit -m "feat(brand): gate content APIs on capabilities, drop duplicate routes"
```

---

## Task 6: Blog draft and published state

**Files:**
- Modify: `brandtechsolution/brand/models.py`, `brand/views.py`, `brand/api_views.py`
- Create: `brandtechsolution/brand/migrations/` — a new migration (let `makemigrations` name it)
- Test: `brandtechsolution/brand/test_blog_status.py`

**Interfaces:**
- Produces: `BlogPost.status` with choices `draft` / `published`, default `draft`.

- [ ] **Step 1: Write the failing test**

Create `brand/test_blog_status.py`:

```python
from django.contrib.auth.models import Permission, User
from django.test import TestCase

from brand.models import BlogPost


def staff_with(*codenames):
    user = User.objects.create_user("cap", password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class BlogStatusModelTest(TestCase):
    def test_new_posts_default_to_draft(self):
        post = BlogPost.objects.create(
            title="t", content="c", excerpt="e", category="cat"
        )
        self.assertEqual(post.status, "draft")


class PublicBlogVisibilityTest(TestCase):
    def setUp(self):
        self.draft = BlogPost.objects.create(
            title="Draft post", content="c", excerpt="e", category="cat",
            status="draft",
        )
        self.live = BlogPost.objects.create(
            title="Live post", content="c", excerpt="e", category="cat",
            status="published",
        )

    def test_blog_list_hides_drafts(self):
        resp = self.client.get("/blog/")
        self.assertContains(resp, "Live post")
        self.assertNotContains(resp, "Draft post")

    def test_blog_detail_404s_for_a_draft(self):
        resp = self.client.get(f"/blog/{self.draft.slug}/")
        self.assertEqual(resp.status_code, 404)

    def test_blog_detail_serves_a_published_post(self):
        resp = self.client.get(f"/blog/{self.live.slug}/")
        self.assertEqual(resp.status_code, 200)


class PublishCapabilityTest(TestCase):
    def setUp(self):
        self.post = BlogPost.objects.create(
            title="t", content="c", excerpt="e", category="cat", status="draft"
        )

    def test_manage_blog_alone_cannot_publish(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            f"/api/posts/{self.post.pk}/",
            {"title": "t", "content": "c", "excerpt": "e",
             "category": "cat", "status": "published"},
        )
        self.assertEqual(resp.status_code, 403)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, "draft")

    def test_manage_blog_can_still_edit_a_draft(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            f"/api/posts/{self.post.pk}/",
            {"title": "edited", "content": "c", "excerpt": "e",
             "category": "cat", "status": "draft"},
        )
        self.assertEqual(resp.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, "edited")

    def test_publish_blog_can_publish(self):
        self.client.force_login(staff_with("manage_blog", "publish_blog"))
        resp = self.client.post(
            f"/api/posts/{self.post.pk}/",
            {"title": "t", "content": "c", "excerpt": "e",
             "category": "cat", "status": "published"},
        )
        self.assertEqual(resp.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, "published")

    def test_unpublishing_also_requires_publish_blog(self):
        self.post.status = "published"
        self.post.save(update_fields=["status"])
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.post(
            f"/api/posts/{self.post.pk}/",
            {"title": "t", "content": "c", "excerpt": "e",
             "category": "cat", "status": "draft"},
        )
        self.assertEqual(resp.status_code, 403)


```

The backfill itself is deliberately not unit-tested. A test asserting that a
migration file exists, or that a blanket `update()` updates rows, proves
nothing about the real risk — which is that the migration runs against
production data in the right order. Step 8 verifies that manually instead.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test brand.test_blog_status --keepdb
```

Expected: FAIL — `BlogPost() got unexpected keyword arguments: 'status'`.

- [ ] **Step 3: Add the field**

In `brand/models.py`, inside `class BlogPost`, add after `featured`:

```python
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
    ]
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='draft', db_index=True
    )
```

- [ ] **Step 4: Generate the migration and add the backfill**

```bash
cd brandtechsolution && .venv/bin/python manage.py makemigrations brand
```

Then edit the generated file. It will contain one `AddField`. Append a `RunPython` after it so existing rows stay visible:

```python
def publish_existing_posts(apps, schema_editor):
    """Every post that existed before this field was added was live.

    The field defaults to 'draft' for new posts, so without this backfill the
    migration would hide the entire public blog.
    """
    BlogPost = apps.get_model("brand", "BlogPost")
    BlogPost.objects.update(status="published")


def noop(apps, schema_editor):
    pass
```

and add to `operations`, after the `AddField`:

```python
        migrations.RunPython(publish_existing_posts, noop),
```

- [ ] **Step 5: Filter the public views**

In `brand/views.py`, change `blog`:

```python
def blog(request):
    """Blog list page (server-rendered, paginated)."""
    post_list = BlogPost.objects.filter(status='published')  # Meta orders by -created_at
    paginator = Paginator(post_list, 9)
    posts = paginator.get_page(request.GET.get("page"))
    return render(request, 'brand/blog.html', {'posts': posts})
```

and `blog_detail`:

```python
def blog_detail(request, slug):
    """Server-rendered individual blog post at /blog/<slug>/."""
    post = get_object_or_404(BlogPost, slug=slug, status='published')
```

- [ ] **Step 6: Gate the transition**

In `brand/api_views.py`, inside `post_detail`, after the existing `manage_blog` check in the POST/PUT branch and before any field is assigned:

```python
        requested_status = request.POST.get('status', post.status)
        if requested_status != post.status:
            denied = capability_required_json(request, 'publish_blog')
            if denied:
                return denied
        post.status = requested_status
```

Publishing and unpublishing are both transitions, so both are gated. In `post_list`'s POST branch, new posts are created as drafts; add nothing there.

Also add `status` to the serialized output of both `post_list` and `post_detail` so the panel can display it. Find the dict each builds and add `'status': post.status,`.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test brand.test_blog_status brand.test_api_permissions --keepdb
```

Expected: OK.

- [ ] **Step 8: Verify the backfill against real data**

Confirm the migration is queued:

```bash
cd brandtechsolution && .venv/bin/python manage.py migrate --plan | tail -5
```

Then prove the backfill actually publishes existing rows, inside a transaction
that is rolled back so the development database is left untouched:

```bash
cd brandtechsolution && .venv/bin/python manage.py shell -c "
from django.db import transaction
from brand.models import BlogPost
print('posts before:', BlogPost.objects.count())
try:
    with transaction.atomic():
        BlogPost.objects.update(status='published')
        print('published after backfill:', BlogPost.objects.filter(status='published').count())
        raise RuntimeError('rollback')
except RuntimeError:
    print('rolled back; database unchanged')
print('still published:', BlogPost.objects.filter(status='published').count())
"
```

Expected: the count after the backfill equals the total post count, and the
final line reports the database unchanged. If the first number is 0 there are
no posts locally and this proves nothing — say so in the task report rather
than claiming it verified.

Do **not** run `migrate` against the development database as part of this task; the deploy does that.

- [ ] **Step 9: Commit**

```bash
git add brandtechsolution/brand
git commit -m "feat(brand): add blog draft state gated by publish_blog"
```

---

## Task 7: Enforce capabilities on appointments

**Files:**
- Modify: `brandtechsolution/appointments/views.py`
- Test: `brandtechsolution/appointments/test_capability_enforcement.py`

- [ ] **Step 1: Write the failing test**

Create `appointments/test_capability_enforcement.py`:

```python
from django.contrib.auth.models import Permission, User
from django.test import TestCase

from appointments.models import Appointment


def staff_with(*codenames):
    user = User.objects.create_user("cap", password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class AppointmentsListCapabilityTest(TestCase):
    def test_staff_without_capability_is_denied(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/appointments/").status_code, 403)

    def test_manage_appointments_is_allowed(self):
        self.client.force_login(staff_with("manage_appointments"))
        self.assertEqual(self.client.get("/appointments/").status_code, 200)

    def test_anonymous_is_redirected(self):
        resp = self.client.get("/appointments/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_superuser_is_allowed(self):
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        self.assertEqual(self.client.get("/appointments/").status_code, 200)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test appointments.test_capability_enforcement --keepdb
```

Expected: FAIL — `200 != 403`, because `test_func` still admits any staff account.

- [ ] **Step 3: Replace the checks**

In `appointments/views.py`, add the import:

```python
from staff.decorators import capability_required
```

Change `AppointmentsListView.test_func` (line 29):

```python
    def test_func(self):
        return self.request.user.has_perm("staff.manage_appointments")
```

`UserPassesTestMixin` raises `PermissionDenied` (403) for a signed-in user who fails the test and redirects an anonymous one, which is the behaviour the tests assert. `has_perm` returns `True` for superusers unconditionally.

Replace the `@staff_member_required` decorator on `admin_manage_appointment` (line 220):

```python
@capability_required("manage_appointments")
def admin_manage_appointment(request, appointment_id):
```

Remove the `staff_member_required` import if nothing else uses it.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test appointments --keepdb
```

Expected: OK. Pre-existing appointments tests that sign in as plain staff will now 403; grant them `manage_appointments` the same way, using the `staff_with` helper.

- [ ] **Step 5: Commit**

```bash
git add brandtechsolution/appointments
git commit -m "feat(appointments): gate staff views on manage_appointments"
```

---

## Task 8: Audit log

**Files:**
- Modify: `brandtechsolution/staff/models.py`
- Create: `brandtechsolution/staff/audit.py`, `staff/migrations/0003_auditentry.py` (generated)
- Test: `brandtechsolution/staff/tests/test_audit.py`

**Interfaces:**
- Produces: `staff.audit.record(actor, action, summary, target_user=None, target_group=None, detail=None) -> AuditEntry`, and `staff.models.AuditEntry` with `ACTION_CHOICES`.

- [ ] **Step 1: Write the failing test**

Create `staff/tests/test_audit.py`:

```python
from django.contrib.auth.models import Group, User
from django.test import TestCase

from staff.audit import record
from staff.models import AuditEntry


class AuditRecordTest(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user("actor", password="p", is_staff=True)
        self.target = User.objects.create_user("target", password="p", is_staff=True)
        self.group = Group.objects.get(name="Editor")

    def test_record_writes_an_entry(self):
        entry = record(
            actor=self.actor,
            action="roles_changed",
            summary="actor changed target's roles to Editor",
            target_user=self.target,
        )
        self.assertEqual(AuditEntry.objects.count(), 1)
        self.assertEqual(entry.actor, self.actor)
        self.assertEqual(entry.action, "roles_changed")

    def test_summary_survives_target_deletion(self):
        """The summary is rendered at write time, so it stays readable."""
        record(
            actor=self.actor,
            action="group_deleted",
            summary="actor deleted the role Editor",
            target_group=self.group,
        )
        self.group.delete()
        entry = AuditEntry.objects.get()
        self.assertEqual(entry.summary, "actor deleted the role Editor")
        self.assertIsNone(entry.target_group)

    def test_actor_deletion_keeps_the_entry(self):
        record(actor=self.actor, action="invite_sent", summary="actor invited x@y.com")
        self.actor.delete()
        entry = AuditEntry.objects.get()
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.summary, "actor invited x@y.com")

    def test_detail_holds_before_and_after(self):
        entry = record(
            actor=self.actor,
            action="group_updated",
            summary="actor changed the Editor role",
            target_group=self.group,
            detail={"before": ["manage_blog"], "after": ["manage_blog", "publish_blog"]},
        )
        entry.refresh_from_db()
        self.assertEqual(entry.detail["after"], ["manage_blog", "publish_blog"])

    def test_entries_are_newest_first(self):
        record(actor=self.actor, action="invite_sent", summary="first")
        record(actor=self.actor, action="invite_sent", summary="second")
        self.assertEqual(
            list(AuditEntry.objects.values_list("summary", flat=True)),
            ["second", "first"],
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff.tests.test_audit --keepdb
```

Expected: FAIL — `ModuleNotFoundError: No module named 'staff.audit'`.

- [ ] **Step 3: Add the model**

Append to `staff/models.py`:

```python
from django.conf import settings


class AuditEntry(models.Model):
    """Append-only record of role and account changes.

    There is no update or delete path in the API. `summary` is rendered when
    the entry is written so it still reads correctly after the user or group
    it names has been deleted.
    """

    ACTION_CHOICES = [
        ("invite_sent", "Invitation sent"),
        ("invite_revoked", "Invitation revoked"),
        ("invite_accepted", "Invitation accepted"),
        ("roles_changed", "Roles changed"),
        ("user_deactivated", "Account deactivated"),
        ("user_reactivated", "Account reactivated"),
        ("group_created", "Role created"),
        ("group_updated", "Role updated"),
        ("group_deleted", "Role deleted"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_actions",
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    target_group = models.ForeignKey(
        "auth.Group", on_delete=models.SET_NULL, null=True, blank=True
    )
    summary = models.TextField()
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "audit entries"

    def __str__(self):
        return self.summary
```

The `-id` tiebreaker matters: two entries written in the same transaction can share a `created_at` to the microsecond, and `test_entries_are_newest_first` would then be flaky.

- [ ] **Step 4: Write the helper**

Create `staff/audit.py`:

```python
from .models import AuditEntry


def record(actor, action, summary, target_user=None, target_group=None, detail=None):
    """Write one audit entry.

    Call inside the same transaction as the change being recorded, so an entry
    is never written for a change that rolled back.
    """
    return AuditEntry.objects.create(
        actor=actor,
        action=action,
        summary=summary,
        target_user=target_user,
        target_group=target_group,
        detail=detail or {},
    )
```

- [ ] **Step 5: Generate the migration**

```bash
cd brandtechsolution && .venv/bin/python manage.py makemigrations staff
```

Expected: `Create model AuditEntry`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/staff
git commit -m "feat(staff): add append-only audit log"
```

---

## Task 9: Roles API

**Files:**
- Create: `brandtechsolution/staff/serializers.py`, `staff/api.py`, `staff/api_urls.py`
- Modify: `brandtechsolution/brandtechsolution/urls.py`
- Test: `brandtechsolution/staff/tests/test_roles_api.py`

**Interfaces:**
- Consumes: `has_capability` (Task 3), `record` (Task 8), `CAPABILITY_GROUPS` (Task 1).
- Produces: routes under `/api/staff/` — `capabilities/` (GET), `roles/` (list, create, retrieve, update, destroy).

- [ ] **Step 1: Write the failing test**

Create `staff/tests/test_roles_api.py`:

```python
import json

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from staff.models import AuditEntry


def staff_with(*codenames, username="cap"):
    user = User.objects.create_user(username, password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class CapabilityListTest(TestCase):
    def test_requires_manage_staff(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/staff/capabilities/").status_code, 403)

    def test_returns_the_grouped_registry(self):
        self.client.force_login(staff_with("manage_staff"))
        resp = self.client.get("/api/staff/capabilities/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual([g["label"] for g in data],
                         ["Content", "Communications", "Administration"])
        flat = [c["codename"] for g in data for c in g["capabilities"]]
        self.assertEqual(len(flat), 11)
        self.assertIn("send_campaigns", flat)


class RoleListTest(TestCase):
    def test_requires_manage_staff(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/staff/roles/").status_code, 403)

    def test_lists_presets_with_member_counts(self):
        user = staff_with("manage_staff")
        Group.objects.get(name="Editor").user_set.add(user)
        self.client.force_login(user)
        resp = self.client.get("/api/staff/roles/")
        self.assertEqual(resp.status_code, 200)
        by_name = {r["name"]: r for r in resp.json()["results"]}
        self.assertEqual(by_name["Editor"]["member_count"], 1)
        self.assertEqual(by_name["Marketing"]["member_count"], 0)
        self.assertIn("manage_blog", by_name["Editor"]["capabilities"])


class RoleWriteTest(TestCase):
    def setUp(self):
        self.admin = staff_with("manage_staff")
        self.client.force_login(self.admin)

    def test_create_a_role(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Interns", "capabilities": ["manage_blog"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        group = Group.objects.get(name="Interns")
        self.assertEqual(
            list(group.permissions.values_list("codename", flat=True)), ["manage_blog"]
        )

    def test_create_writes_an_audit_entry(self):
        self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Interns", "capabilities": []}),
            content_type="application/json",
        )
        entry = AuditEntry.objects.get(action="group_created")
        self.assertEqual(entry.actor, self.admin)
        self.assertIn("Interns", entry.summary)

    def test_update_replaces_capabilities_and_records_before_after(self):
        group = Group.objects.get(name="Editor")
        resp = self.client.put(
            f"/api/staff/roles/{group.pk}/",
            json.dumps({"name": "Editor", "capabilities": ["view_inbox"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            list(group.permissions.values_list("codename", flat=True)), ["view_inbox"]
        )
        entry = AuditEntry.objects.get(action="group_updated")
        self.assertIn("manage_blog", entry.detail["before"])
        self.assertEqual(entry.detail["after"], ["view_inbox"])

    def test_unknown_capability_is_rejected(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Bad", "capabilities": ["not_a_capability"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Group.objects.filter(name="Bad").exists())

    def test_duplicate_name_is_rejected(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Editor", "capabilities": []}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_delete_a_role(self):
        group = Group.objects.get(name="Support")
        resp = self.client.delete(f"/api/staff/roles/{group.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Group.objects.filter(name="Support").exists())
        self.assertTrue(AuditEntry.objects.filter(action="group_deleted").exists())
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff.tests.test_roles_api --keepdb
```

Expected: FAIL — 404 on every route.

- [ ] **Step 3: Write the serializer**

Create `staff/serializers.py`:

```python
from django.contrib.auth.models import Group, Permission
from rest_framework import serializers

from .capabilities import CODENAMES


class RoleSerializer(serializers.ModelSerializer):
    capabilities = serializers.ListField(
        child=serializers.CharField(), allow_empty=True
    )
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = ["id", "name", "capabilities", "member_count"]

    def validate_capabilities(self, value):
        unknown = sorted(set(value) - set(CODENAMES))
        if unknown:
            raise serializers.ValidationError(
                f"Unknown capabilities: {', '.join(unknown)}"
            )
        return value

    def _apply(self, group, codenames):
        group.permissions.set(
            Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )

    def create(self, validated_data):
        codenames = validated_data.pop("capabilities")
        group = Group.objects.create(**validated_data)
        self._apply(group, codenames)
        return group

    def update(self, instance, validated_data):
        codenames = validated_data.pop("capabilities", None)
        instance.name = validated_data.get("name", instance.name)
        instance.save()
        if codenames is not None:
            self._apply(instance, codenames)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["capabilities"] = sorted(
            instance.permissions.filter(
                content_type__app_label="staff"
            ).values_list("codename", flat=True)
        )
        return data
```

`Group.name` is already unique, so DRF derives the duplicate-name check automatically and `test_duplicate_name_is_rejected` passes without extra code.

- [ ] **Step 4: Write the API**

Create `staff/api.py`:

```python
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .audit import record
from .capabilities import CAPABILITY_GROUPS
from .permissions import has_capability
from .serializers import RoleSerializer


class StaffPagination(PageNumberPagination):
    page_size = 50


@api_view(["GET"])
@permission_classes([has_capability("manage_staff")])
def capabilities(request):
    """The capability registry, grouped as the UI displays it."""
    return Response([
        {
            "label": label,
            "capabilities": [
                {"codename": codename, "label": text} for codename, text in pairs
            ],
        }
        for label, pairs in CAPABILITY_GROUPS
    ])


class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        return Group.objects.annotate(member_count=Count("user")).order_by("name")

    def _codenames(self, group):
        return sorted(
            group.permissions.filter(
                content_type__app_label="staff"
            ).values_list("codename", flat=True)
        )

    def perform_create(self, serializer):
        with transaction.atomic():
            group = serializer.save()
            record(
                actor=self.request.user,
                action="group_created",
                summary=f"{self.request.user} created the role {group.name}",
                target_group=group,
                detail={"after": self._codenames(group)},
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            before = self._codenames(serializer.instance)
            group = serializer.save()
            record(
                actor=self.request.user,
                action="group_updated",
                summary=f"{self.request.user} changed the role {group.name}",
                target_group=group,
                detail={"before": before, "after": self._codenames(group)},
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            name = instance.name
            codenames = self._codenames(instance)
            record(
                actor=self.request.user,
                action="group_deleted",
                summary=f"{self.request.user} deleted the role {name}",
                detail={"before": codenames, "name": name},
            )
            instance.delete()
```

`perform_destroy` records *before* deleting and does not set `target_group`, because the row is about to disappear and `SET_NULL` would blank it anyway. The name lives in `summary` and `detail`.

- [ ] **Step 5: Wire the routes**

Create `staff/api_urls.py`:

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register(r"roles", api.RoleViewSet, basename="roles")

urlpatterns = [
    path("", include(router.urls)),
    path("capabilities/", api.capabilities, name="capabilities"),
]
```

In `brandtechsolution/brandtechsolution/urls.py`, add alongside the other API includes:

```python
    path('api/staff/', include('staff.api_urls')),
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add brandtechsolution/staff brandtechsolution/brandtechsolution/urls.py
git commit -m "feat(staff): add roles API with audit trail"
```

---

## Task 10: People API and self-lockout rules

**Files:**
- Modify: `brandtechsolution/staff/serializers.py`, `staff/api.py`, `staff/api_urls.py`
- Test: `brandtechsolution/staff/tests/test_people_api.py`

**Interfaces:**
- Produces: `/api/staff/people/` — list; `PATCH /api/staff/people/<pk>/` to change roles and active state.

**Rules:** only `is_staff=True` users appear. A non-superuser may not edit their own roles or deactivate themselves. Superusers are exempt from both rules.

- [ ] **Step 1: Write the failing test**

Create `staff/tests/test_people_api.py`:

```python
import json

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from staff.models import AuditEntry


def staff_with(*codenames, username="cap"):
    user = User.objects.create_user(username, password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class PeopleListTest(TestCase):
    def test_requires_manage_staff(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/staff/people/").status_code, 403)

    def test_lists_only_staff_accounts(self):
        admin = staff_with("manage_staff")
        User.objects.create_user("public_signup", password="p")  # not staff
        self.client.force_login(admin)
        resp = self.client.get("/api/staff/people/")
        usernames = [p["username"] for p in resp.json()["results"]]
        self.assertIn("cap", usernames)
        self.assertNotIn("public_signup", usernames)

    def test_includes_roles_and_active_state(self):
        admin = staff_with("manage_staff")
        Group.objects.get(name="Editor").user_set.add(admin)
        self.client.force_login(admin)
        person = self.client.get("/api/staff/people/").json()["results"][0]
        self.assertEqual(person["roles"], ["Editor"])
        self.assertTrue(person["is_active"])


class RoleAssignmentTest(TestCase):
    def setUp(self):
        self.admin = staff_with("manage_staff", username="admin")
        self.target = staff_with(username="target")
        self.client.force_login(self.admin)

    def test_assign_roles(self):
        editor = Group.objects.get(name="Editor")
        resp = self.client.patch(
            f"/api/staff/people/{self.target.pk}/",
            json.dumps({"role_ids": [editor.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(self.target.groups.all()), [editor])

    def test_assignment_is_audited(self):
        editor = Group.objects.get(name="Editor")
        self.client.patch(
            f"/api/staff/people/{self.target.pk}/",
            json.dumps({"role_ids": [editor.pk]}),
            content_type="application/json",
        )
        entry = AuditEntry.objects.get(action="roles_changed")
        self.assertEqual(entry.target_user, self.target)
        self.assertEqual(entry.detail["after"], ["Editor"])

    def test_deactivate_a_user(self):
        resp = self.client.patch(
            f"/api/staff/people/{self.target.pk}/",
            json.dumps({"is_active": False}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertTrue(AuditEntry.objects.filter(action="user_deactivated").exists())

    def test_reactivate_a_user(self):
        self.target.is_active = False
        self.target.save(update_fields=["is_active"])
        self.client.patch(
            f"/api/staff/people/{self.target.pk}/",
            json.dumps({"is_active": True}),
            content_type="application/json",
        )
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertTrue(AuditEntry.objects.filter(action="user_reactivated").exists())


class SelfLockoutTest(TestCase):
    def setUp(self):
        self.admin = staff_with("manage_staff", username="admin")
        self.client.force_login(self.admin)

    def test_cannot_change_own_roles(self):
        editor = Group.objects.get(name="Editor")
        resp = self.client.patch(
            f"/api/staff/people/{self.admin.pk}/",
            json.dumps({"role_ids": [editor.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(list(self.admin.groups.all()), [])

    def test_cannot_deactivate_self(self):
        resp = self.client.patch(
            f"/api/staff/people/{self.admin.pk}/",
            json.dumps({"is_active": False}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_superuser_may_edit_own_roles(self):
        root = User.objects.create_superuser("root", password="p")
        self.client.force_login(root)
        editor = Group.objects.get(name="Editor")
        resp = self.client.patch(
            f"/api/staff/people/{root.pk}/",
            json.dumps({"role_ids": [editor.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff.tests.test_people_api --keepdb
```

Expected: FAIL — 404 on every route.

- [ ] **Step 3: Write the serializer**

Append to `staff/serializers.py`:

```python
from django.contrib.auth.models import User


class PersonSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    role_ids = serializers.PrimaryKeyRelatedField(
        source="groups", queryset=Group.objects.all(), many=True, write_only=True,
        required=False,
    )

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "is_active", "is_superuser", "roles", "role_ids", "date_joined",
        ]
        read_only_fields = ["username", "is_superuser", "date_joined"]

    def get_roles(self, obj):
        return sorted(g.name for g in obj.groups.all())
```

- [ ] **Step 4: Write the viewset**

Append to `staff/api.py`:

```python
from django.contrib.auth.models import User
from rest_framework import mixins
from rest_framework.exceptions import PermissionDenied

from .serializers import PersonSerializer


class PersonViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Staff accounts. Creation happens through invitations, not here."""

    serializer_class = PersonSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        return User.objects.filter(is_staff=True).prefetch_related("groups").order_by(
            "username"
        )

    def perform_update(self, serializer):
        actor = self.request.user
        target = serializer.instance

        # A non-superuser editing themselves could drop manage_staff or switch
        # off their own account and lock the panel. One flat rule beats
        # last-admin-standing arithmetic; superusers remain the escape hatch.
        if target.pk == actor.pk and not actor.is_superuser:
            raise PermissionDenied(
                "You cannot change your own roles or deactivate your own account."
            )

        with transaction.atomic():
            before_roles = sorted(g.name for g in target.groups.all())
            was_active = target.is_active
            person = serializer.save()
            after_roles = sorted(g.name for g in person.groups.all())

            if after_roles != before_roles:
                record(
                    actor=actor,
                    action="roles_changed",
                    summary=(
                        f"{actor} changed {person}'s roles to "
                        f"{', '.join(after_roles) or 'none'}"
                    ),
                    target_user=person,
                    detail={"before": before_roles, "after": after_roles},
                )

            if person.is_active != was_active:
                action = "user_reactivated" if person.is_active else "user_deactivated"
                verb = "reactivated" if person.is_active else "deactivated"
                record(
                    actor=actor,
                    action=action,
                    summary=f"{actor} {verb} {person}",
                    target_user=person,
                )
```

Register it in `staff/api_urls.py`:

```python
router.register(r"people", api.PersonViewSet, basename="people")
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add brandtechsolution/staff
git commit -m "feat(staff): add people API with self-lockout protection"
```

---

## Task 11: Invitations

**Files:**
- Modify: `brandtechsolution/staff/models.py`, `staff/serializers.py`, `staff/api.py`, `staff/api_urls.py`
- Create: `brandtechsolution/staff/tokens.py`, `staff/emails.py`, `staff/views.py`, `staff/urls.py`, `staff/templates/staff/accept_invitation.html`, migration (generated)
- Modify: `brandtechsolution/brandtechsolution/urls.py`
- Test: `brandtechsolution/staff/tests/test_invitations.py`

**Interfaces:**
- Produces: `staff.tokens.make_invitation_token(invitation_id) -> str`, `staff.tokens.read_invitation_token(token) -> int` (raises `signing.BadSignature` / `signing.SignatureExpired`), `staff.models.StaffInvitation`, and the route `/staff/invite/<token>/`.

- [ ] **Step 1: Write the failing test**

Create `staff/tests/test_invitations.py`:

```python
import json

from django.contrib.auth.models import Group, Permission, User
from django.core import mail, signing
from django.test import TestCase
from django.utils import timezone

from staff.models import AuditEntry, StaffInvitation
from staff.tokens import make_invitation_token


def staff_with(*codenames, username="cap"):
    user = User.objects.create_user(username, password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class InvitationCreateTest(TestCase):
    def setUp(self):
        self.admin = staff_with("manage_staff", username="admin")
        self.client.force_login(self.admin)
        self.editor = Group.objects.get(name="Editor")

    def _invite(self, email="new@example.com"):
        return self.client.post(
            "/api/staff/invitations/",
            json.dumps({"email": email, "role_ids": [self.editor.pk]}),
            content_type="application/json",
        )

    def test_requires_manage_staff(self):
        self.client.force_login(staff_with(username="nobody"))
        self.assertEqual(self._invite().status_code, 403)

    def test_creates_an_invitation_without_a_user(self):
        resp = self._invite()
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(StaffInvitation.objects.filter(email="new@example.com").exists())
        self.assertFalse(User.objects.filter(username="new@example.com").exists())

    def test_sends_an_email_containing_the_link(self):
        self._invite()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("new@example.com", mail.outbox[0].to)
        self.assertIn("/staff/invite/", mail.outbox[0].body)

    def test_email_is_lowercased(self):
        self._invite("MixedCase@Example.COM")
        self.assertTrue(
            StaffInvitation.objects.filter(email="mixedcase@example.com").exists()
        )

    def test_is_audited(self):
        self._invite()
        entry = AuditEntry.objects.get(action="invite_sent")
        self.assertEqual(entry.actor, self.admin)
        self.assertIn("new@example.com", entry.summary)

    def test_existing_account_is_refused(self):
        User.objects.create_user("taken@example.com", password="p", is_staff=True)
        resp = self._invite("taken@example.com")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already", json.dumps(resp.json()).lower())

    def test_duplicate_pending_invitation_is_refused(self):
        self._invite()
        self.assertEqual(self._invite().status_code, 400)


class InvitationAcceptTest(TestCase):
    def setUp(self):
        self.editor = Group.objects.get(name="Editor")
        self.invitation = StaffInvitation.objects.create(
            email="new@example.com",
            invited_by=staff_with("manage_staff", username="admin"),
        )
        self.invitation.groups.add(self.editor)
        self.token = make_invitation_token(self.invitation.pk)

    def test_get_shows_the_form(self):
        resp = self.client.get(f"/staff/invite/{self.token}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "new@example.com")

    def test_post_creates_a_staff_user_with_the_roles(self):
        resp = self.client.post(
            f"/staff/invite/{self.token}/",
            {"password1": "a-good-password-42", "password2": "a-good-password-42"},
        )
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username="new@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("a-good-password-42"))
        self.assertEqual(list(user.groups.all()), [self.editor])

    def test_acceptance_is_recorded_and_audited(self):
        self.client.post(
            f"/staff/invite/{self.token}/",
            {"password1": "a-good-password-42", "password2": "a-good-password-42"},
        )
        self.invitation.refresh_from_db()
        self.assertIsNotNone(self.invitation.accepted_at)
        self.assertTrue(AuditEntry.objects.filter(action="invite_accepted").exists())

    def test_mismatched_passwords_are_rejected(self):
        resp = self.client.post(
            f"/staff/invite/{self.token}/",
            {"password1": "a-good-password-42", "password2": "different-42"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="new@example.com").exists())

    def test_a_token_cannot_be_used_twice(self):
        payload = {"password1": "a-good-password-42", "password2": "a-good-password-42"}
        self.client.post(f"/staff/invite/{self.token}/", payload)
        resp = self.client.post(f"/staff/invite/{self.token}/", payload)
        self.assertEqual(resp.status_code, 410)
        self.assertEqual(User.objects.filter(username="new@example.com").count(), 1)

    def test_a_revoked_invitation_rejects_its_token(self):
        self.invitation.delete()
        resp = self.client.get(f"/staff/invite/{self.token}/")
        self.assertEqual(resp.status_code, 410)

    def test_a_tampered_token_is_rejected(self):
        resp = self.client.get(f"/staff/invite/{self.token}xyz/")
        self.assertEqual(resp.status_code, 410)

    def test_an_expired_token_is_rejected(self):
        from staff import tokens

        stale = signing.dumps(
            {"id": self.invitation.pk}, salt=tokens.INVITATION_SALT
        )
        # max_age is measured from the signature timestamp. A negative max_age
        # expires any token deterministically, with no sleep and no dependence
        # on how many microseconds the test took.
        with self.settings(STAFF_INVITATION_MAX_AGE=-1):
            resp = self.client.get(f"/staff/invite/{stale}/")
        self.assertEqual(resp.status_code, 410)

    def test_a_valid_token_is_accepted_within_the_window(self):
        """Guards against the expiry check rejecting everything."""
        resp = self.client.get(f"/staff/invite/{self.token}/")
        self.assertEqual(resp.status_code, 200)


class InvitationRevokeTest(TestCase):
    def test_revoking_deletes_the_invitation_and_audits(self):
        admin = staff_with("manage_staff", username="admin")
        invitation = StaffInvitation.objects.create(
            email="new@example.com", invited_by=admin
        )
        self.client.force_login(admin)
        resp = self.client.delete(f"/api/staff/invitations/{invitation.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(StaffInvitation.objects.filter(pk=invitation.pk).exists())
        self.assertTrue(AuditEntry.objects.filter(action="invite_revoked").exists())
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff.tests.test_invitations --keepdb
```

Expected: FAIL — `ModuleNotFoundError: No module named 'staff.tokens'`.

- [ ] **Step 3: Add the model**

Append to `staff/models.py`:

```python
class StaffInvitation(models.Model):
    """A pending staff account. No User row exists until it is accepted."""

    email = models.EmailField(unique=True)
    groups = models.ManyToManyField("auth.Group", blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="invitations_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.email
```

Generate the migration:

```bash
cd brandtechsolution && .venv/bin/python manage.py makemigrations staff
```

- [ ] **Step 4: Write the token helpers**

Create `staff/tokens.py`:

```python
from django.conf import settings
from django.core import signing

INVITATION_SALT = "staff.invite"
DEFAULT_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def make_invitation_token(invitation_id: int) -> str:
    return signing.dumps({"id": invitation_id}, salt=INVITATION_SALT)


def read_invitation_token(token: str) -> int:
    """Return the invitation id.

    Raises signing.SignatureExpired if older than the configured max age, or
    signing.BadSignature if tampered with.
    """
    max_age = getattr(settings, "STAFF_INVITATION_MAX_AGE", DEFAULT_MAX_AGE)
    return signing.loads(token, salt=INVITATION_SALT, max_age=max_age)["id"]
```

This mirrors `messaging/tokens.py`, which already signs values with a salt.

- [ ] **Step 5: Write the email helper**

Create `staff/emails.py`:

```python
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from .tokens import make_invitation_token


def send_invitation(invitation, request=None):
    """Send the invitation link.

    Sent directly rather than through the campaign outbox: an invitation is
    transactional and must not queue behind a bulk send.
    """
    path = reverse(
        "staff:accept-invitation",
        kwargs={"token": make_invitation_token(invitation.pk)},
    )
    url = request.build_absolute_uri(path) if request else path
    inviter = invitation.invited_by or "An administrator"

    send_mail(
        subject="You have been invited to the Teklora admin panel",
        message=(
            f"{inviter} has invited you to the Teklora admin panel.\n\n"
            f"Set your password to activate your account:\n{url}\n\n"
            "This link expires in 7 days. If you were not expecting this "
            "invitation you can ignore this message."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invitation.email],
        fail_silently=False,
    )
```

If `DEFAULT_FROM_EMAIL` is not set in `settings.py`, add `DEFAULT_FROM_EMAIL = EMAIL_HOST_USER` near the other email settings.

- [ ] **Step 6: Write the invitation API**

Append to `staff/serializers.py`:

```python
from .models import StaffInvitation


class InvitationSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    role_ids = serializers.PrimaryKeyRelatedField(
        source="groups", queryset=Group.objects.all(), many=True, write_only=True,
        required=False,
    )

    class Meta:
        model = StaffInvitation
        fields = ["id", "email", "roles", "role_ids", "created_at", "accepted_at"]
        read_only_fields = ["created_at", "accepted_at"]

    def get_roles(self, obj):
        return sorted(g.name for g in obj.groups.all())

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(username__iexact=email).exists() or \
                User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "An account with this email already exists. "
                "Edit that person's roles instead."
            )
        return email
```

`StaffInvitation.email` is unique, so DRF rejects a duplicate pending invitation automatically.

Append to `staff/api.py`:

```python
from .emails import send_invitation
from .models import StaffInvitation
from .serializers import InvitationSerializer


class InvitationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = InvitationSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        return StaffInvitation.objects.filter(
            accepted_at__isnull=True
        ).prefetch_related("groups")

    def perform_create(self, serializer):
        with transaction.atomic():
            invitation = serializer.save(invited_by=self.request.user)
            record(
                actor=self.request.user,
                action="invite_sent",
                summary=f"{self.request.user} invited {invitation.email}",
                detail={"email": invitation.email,
                        "roles": sorted(g.name for g in invitation.groups.all())},
            )
        # Sent after the transaction commits: a failed send must not leave a
        # committed audit entry describing an email that never went out.
        send_invitation(invitation, self.request)

    def perform_destroy(self, instance):
        with transaction.atomic():
            record(
                actor=self.request.user,
                action="invite_revoked",
                summary=f"{self.request.user} revoked the invitation to {instance.email}",
                detail={"email": instance.email},
            )
            instance.delete()
```

Register it in `staff/api_urls.py`:

```python
router.register(r"invitations", api.InvitationViewSet, basename="invitations")
```

- [ ] **Step 7: Write the acceptance view**

Create `staff/views.py`:

```python
from django.contrib.auth.models import User
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .audit import record
from .models import StaffInvitation
from .tokens import read_invitation_token

GONE = "This invitation link is no longer valid. Ask an administrator for a new one."


def accept_invitation(request, token):
    try:
        invitation_id = read_invitation_token(token)
    except (signing.BadSignature, signing.SignatureExpired):
        return HttpResponse(GONE, status=410)

    invitation = StaffInvitation.objects.filter(
        pk=invitation_id, accepted_at__isnull=True
    ).first()
    if invitation is None:
        return HttpResponse(GONE, status=410)

    if request.method != "POST":
        return render(
            request, "staff/accept_invitation.html", {"invitation": invitation}
        )

    password1 = request.POST.get("password1") or ""
    password2 = request.POST.get("password2") or ""
    error = None
    if password1 != password2:
        error = "The two passwords do not match."
    elif len(password1) < 10:
        error = "Choose a password of at least 10 characters."

    if error:
        return render(
            request,
            "staff/accept_invitation.html",
            {"invitation": invitation, "error": error},
        )

    with transaction.atomic():
        # Claim the invitation before creating anything. If a second request
        # got here first this updates zero rows and we stop, so one link can
        # never mint two accounts. Same guarded-update pattern the outbox uses.
        claimed = StaffInvitation.objects.filter(
            pk=invitation.pk, accepted_at__isnull=True
        ).update(accepted_at=timezone.now())
        if not claimed:
            return HttpResponse(GONE, status=410)

        user = User.objects.create_user(
            username=invitation.email, email=invitation.email, is_staff=True
        )
        user.set_password(password1)
        user.save()
        user.groups.set(invitation.groups.all())

        record(
            actor=None,
            action="invite_accepted",
            summary=f"{invitation.email} accepted their invitation",
            target_user=user,
            detail={"roles": sorted(g.name for g in user.groups.all())},
        )

    return redirect("/login/")
```

Create `staff/urls.py`:

```python
from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("invite/<str:token>/", views.accept_invitation, name="accept-invitation"),
]
```

In `brandtechsolution/brandtechsolution/urls.py`:

```python
    path('staff/', include('staff.urls')),
```

- [ ] **Step 8: Write the acceptance template**

Create `staff/templates/staff/accept_invitation.html`:

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Set your password</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0B0F17] text-white min-h-screen flex items-center justify-center p-4">
    <div class="w-full max-w-md bg-[#111827] border border-white/10 rounded-xl p-8">
        <h1 class="text-2xl font-bold mb-2">Set your password</h1>
        <p class="text-gray-400 text-sm mb-6">
            You were invited as <span class="text-white">{{ invitation.email }}</span>.
        </p>

        {% if error %}
        <p class="mb-4 text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
            {{ error }}
        </p>
        {% endif %}

        <form method="post" class="space-y-4">
            {% csrf_token %}
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">Password</label>
                <input type="password" name="password1" required minlength="10"
                    class="w-full bg-[#06090F] border border-white/10 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500">
            </div>
            <div>
                <label class="block text-sm font-medium text-gray-400 mb-2">Confirm password</label>
                <input type="password" name="password2" required minlength="10"
                    class="w-full bg-[#06090F] border border-white/10 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500">
            </div>
            <button type="submit"
                class="w-full bg-blue-600 hover:bg-blue-500 font-semibold px-5 py-3 rounded-lg">
                Activate my account
            </button>
        </form>
    </div>
</body>
</html>
```

Django auto-escapes `{{ invitation.email }}`, so no extra handling is needed here.

- [ ] **Step 9: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: OK.

- [ ] **Step 10: Commit**

```bash
git add brandtechsolution/staff brandtechsolution/brandtechsolution/urls.py
git commit -m "feat(staff): add email invitations with single-use tokens"
```

---

## Task 12: Panel UI

**Files:**
- Create: `brandtechsolution/brand/templates/brand/admin/_staff.html`, `brand/static/brand/js/admin/staff.js`
- Modify: `brandtechsolution/brand/templates/brand/admin_panel.html`, `brand/views.py`, `brand/static/brand/js/admin/core.js`, `brand/static/brand/js/admin/campaigns.js`
- Test: `brandtechsolution/staff/tests/test_panel_rendering.py`

**Interfaces:**
- Consumes: every API from Tasks 9-11.
- Produces: `window.CAPABILITIES` — a JS array of capability codenames held by the current user.

- [ ] **Step 1: Write the failing test**

Create `staff/tests/test_panel_rendering.py`:

```python
from django.contrib.auth.models import Permission, User
from django.test import TestCase


def staff_with(*codenames, username="cap"):
    user = User.objects.create_user(username, password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class NavGatingTest(TestCase):
    def test_staff_nav_hidden_without_manage_staff(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/admin-panel/")
        self.assertNotContains(resp, "showSection('staff'")

    def test_staff_nav_shown_with_manage_staff(self):
        self.client.force_login(staff_with("manage_staff"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, "showSection('staff'")

    def test_campaigns_nav_hidden_without_capability(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/admin-panel/")
        self.assertNotContains(resp, "showSection('campaigns'")

    def test_superuser_sees_everything(self):
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, "showSection('staff'")
        self.assertContains(resp, "showSection('campaigns'")


class CapabilityExposureTest(TestCase):
    def test_capabilities_are_exposed_to_javascript(self):
        self.client.force_login(staff_with("manage_blog", "view_inbox"))
        resp = self.client.get("/admin-panel/")
        self.assertContains(resp, "window.CAPABILITIES")
        self.assertContains(resp, "manage_blog")
        self.assertContains(resp, "view_inbox")

    def test_capabilities_not_held_are_absent(self):
        self.client.force_login(staff_with("manage_blog"))
        resp = self.client.get("/admin-panel/")
        self.assertNotContains(resp, "send_campaigns")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff.tests.test_panel_rendering --keepdb
```

Expected: FAIL — the nav renders unconditionally, so the "hidden" assertions fail.

- [ ] **Step 3: Pass capabilities into the template**

In `brand/views.py`, replace `admin_panel_page`:

```python
from staff.capabilities import CODENAMES


@login_required(login_url='/login/')
@user_passes_test(is_admin, login_url='/login/')
def admin_panel_page(request):
    held = sorted(c for c in CODENAMES if request.user.has_perm(f'staff.{c}'))
    return render(request, 'brand/admin_panel.html', {
        'capabilities': held,
        'can': {c: True for c in held},
    })
```

`can` gives the template dictionary-style lookups (`{% if can.manage_staff %}`), which Django templates support and which read better than a list membership test.

- [ ] **Step 4: Gate the nav and expose the capability set**

In `brand/templates/brand/admin_panel.html`, wrap each nav link in its capability check. For example:

```html
{% if can.manage_blog %}
<a href="#" onclick="showSection('blogs', this)"
    class="nav-item flex items-center px-4 py-3 text-sm font-medium rounded-lg text-gray-400 transition-colors">
    <i class="fas fa-pen-nib w-6 text-center mr-3"></i>Blog Posts
</a>
{% endif %}
```

Apply the same pattern using: `can.manage_projects` for Projects, `can.manage_appointments` for Appointments, `can.view_inbox` for Inbox, `can.manage_templates` for Templates, `can.manage_campaigns` for Campaigns. Leave Dashboard ungated.

Add the Staff nav item after Campaigns, inside its own Administration heading:

```html
{% if can.manage_staff %}
<div class="pt-4 pb-2 px-4 text-xs font-semibold text-gray-600 uppercase tracking-wider">Administration</div>
<a href="#" onclick="showSection('staff', this)"
    class="nav-item flex items-center px-4 py-3 text-sm font-medium rounded-lg text-gray-400 transition-colors">
    <i class="fas fa-users-gear w-6 text-center mr-3"></i>Staff &amp; Roles
</a>
{% endif %}
```

Include the new section alongside the others:

```html
{% if can.manage_staff %}
    {% include 'brand/admin/_staff.html' %}
{% endif %}
```

Expose the capability set to JavaScript. Add this immediately **before** the `core.js` script tag:

```html
{{ capabilities|json_script:"capabilityData" }}
<script>
    window.CAPABILITIES = JSON.parse(document.getElementById('capabilityData').textContent);
    window.can = (codename) => window.CAPABILITIES.includes(codename);
</script>
```

`json_script` escapes the payload safely; never interpolate this list into JavaScript by hand.

Load the new script after `recipients.js`:

```html
<script src="{% static 'brand/js/admin/staff.js' %}" defer></script>
```

- [ ] **Step 5: Guard the section loaders**

In `brand/static/brand/js/admin/core.js`, add to `showSection`:

```javascript
    if (sectionName === 'staff') loadStaff();
```

- [ ] **Step 6: Build the section template**

Create `brand/templates/brand/admin/_staff.html`:

```html
<div id="staff" class="section hidden">
    <div class="flex justify-between items-center mb-8 gap-4">
        <div>
            <h2 class="text-2xl font-bold text-white">Staff &amp; Roles</h2>
            <p class="text-gray-500 text-sm">Who can use this panel, and what they can do</p>
        </div>
        <button type="button" id="inviteBtn"
            class="bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-2.5 rounded-lg flex items-center">
            <i class="fas fa-user-plus mr-2"></i>Invite person
        </button>
    </div>

    <div class="flex gap-2 mb-6 border-b border-dark-border">
        <button type="button" data-tab="people"
            class="staff-tab px-4 py-2 text-sm font-medium text-white border-b-2 border-brand-blue">People</button>
        <button type="button" data-tab="roles"
            class="staff-tab px-4 py-2 text-sm font-medium text-gray-400 border-b-2 border-transparent">Roles</button>
        <button type="button" data-tab="activity"
            class="staff-tab px-4 py-2 text-sm font-medium text-gray-400 border-b-2 border-transparent">Activity</button>
    </div>

    <div id="staffPeople" class="staff-pane">
        <div id="staffPeopleList" class="space-y-3"></div>
    </div>

    <div id="staffRoles" class="staff-pane hidden">
        <button type="button" id="newRoleBtn"
            class="mb-4 px-4 py-2 text-sm rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">
            <i class="fas fa-plus mr-2"></i>New role
        </button>
        <div id="staffRolesList" class="space-y-3"></div>
    </div>

    <div id="staffActivity" class="staff-pane hidden">
        <div id="staffActivityList" class="space-y-2"></div>
    </div>
</div>

<div id="staffModal" class="fixed inset-0 bg-black/70 z-50 hidden items-center justify-center p-4">
    <div class="bg-dark-card border border-dark-border rounded-xl w-full max-w-lg max-h-[85vh] overflow-y-auto p-6">
        <div class="flex justify-between items-center mb-6">
            <h3 id="staffModalTitle" class="text-lg font-bold text-white">Invite person</h3>
            <button type="button" id="staffModalClose" class="text-gray-400 hover:text-white">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div id="staffModalBody"></div>
    </div>
</div>
```

- [ ] **Step 7: Add the audit log endpoint**

`staff.js` in the next step reads `/api/staff/activity/`, so build it first.

Add to `staff/serializers.py`:

```python
from .models import AuditEntry


class AuditEntrySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", default="system",
                                       read_only=True)

    class Meta:
        model = AuditEntry
        fields = ["id", "action", "summary", "actor_name", "created_at"]
```

Add to `staff/api.py`:

```python
from .models import AuditEntry
from .serializers import AuditEntrySerializer


class AuditViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Read-only by construction: there is no create, update or delete route."""

    serializer_class = AuditEntrySerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination
    queryset = AuditEntry.objects.select_related("actor", "target_user", "target_group")
```

Register it in `staff/api_urls.py`:

```python
router.register(r"activity", api.AuditViewSet, basename="activity")
```

- [ ] **Step 8: Write the JavaScript**

Create `brand/static/brand/js/admin/staff.js`:

```javascript
const STAFF_API = '/api/staff';
let CAPABILITY_GROUPS = [];
let ROLES = [];

async function staffFetch(path, options = {}) {
    const response = await fetch(`${STAFF_API}${path}`, {
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': CSRF_TOKEN, 'Content-Type': 'application/json' },
        ...options,
    });
    if (!response.ok && response.status !== 204) {
        let detail = 'Request failed';
        try {
            const body = await response.json();
            detail = typeof body === 'string' ? body : JSON.stringify(body);
        } catch (e) { /* response had no JSON body */ }
        throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
}

async function loadStaff() {
    try {
        if (!CAPABILITY_GROUPS.length) {
            CAPABILITY_GROUPS = await staffFetch('/capabilities/');
        }
        await Promise.all([loadPeople(), loadRoles(), loadActivity()]);
    } catch (e) {
        console.error(e);
        alert(`Could not load staff data: ${e.message}`);
    }
}

async function loadPeople() {
    const [people, invitations] = await Promise.all([
        staffFetch('/people/'),
        staffFetch('/invitations/'),
    ]);

    const inviteRows = invitations.results.map(inv => `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex justify-between items-center gap-4">
            <div>
                <div class="text-white font-medium">${escapeHtml(inv.email)}</div>
                <div class="text-xs text-gray-500">Invited &middot; ${escapeHtml(inv.roles.join(', ') || 'no roles')}</div>
            </div>
            <div class="flex items-center gap-2">
                <span class="text-xs px-2 py-1 rounded bg-yellow-500/10 text-yellow-400">Pending</span>
                <button type="button" data-action="revoke-invite" data-id="${inv.id}"
                    class="text-xs text-red-400 hover:text-red-300">Revoke</button>
            </div>
        </div>`).join('');

    const peopleRows = people.results.map(p => `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex justify-between items-center gap-4">
            <div>
                <div class="text-white font-medium">${escapeHtml(p.username)}</div>
                <div class="text-xs text-gray-500">${escapeHtml(p.roles.join(', ') || 'no roles')}</div>
            </div>
            <div class="flex items-center gap-2">
                ${p.is_superuser ? '<span class="text-xs px-2 py-1 rounded bg-purple-500/10 text-purple-400">Superuser</span>' : ''}
                <span class="text-xs px-2 py-1 rounded ${p.is_active ? 'bg-green-500/10 text-green-400' : 'bg-gray-500/10 text-gray-400'}">
                    ${p.is_active ? 'Active' : 'Deactivated'}
                </span>
                <button type="button" data-action="edit-person" data-id="${p.id}"
                    class="text-xs text-brand-blue hover:text-blue-400">Edit roles</button>
            </div>
        </div>`).join('');

    document.getElementById('staffPeopleList').innerHTML =
        inviteRows + peopleRows || '<p class="text-gray-500 text-sm">Nobody yet.</p>';
}

async function loadRoles() {
    const data = await staffFetch('/roles/');
    ROLES = data.results;
    document.getElementById('staffRolesList').innerHTML = ROLES.map(role => `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex justify-between items-center gap-4">
            <div>
                <div class="text-white font-medium">${escapeHtml(role.name)}</div>
                <div class="text-xs text-gray-500">
                    ${role.member_count} member${role.member_count === 1 ? '' : 's'}
                    &middot; ${role.capabilities.length} capabilit${role.capabilities.length === 1 ? 'y' : 'ies'}
                </div>
            </div>
            <div class="flex items-center gap-3">
                <button type="button" data-action="edit-role" data-id="${role.id}"
                    class="text-xs text-brand-blue hover:text-blue-400">Edit</button>
                <button type="button" data-action="delete-role" data-id="${role.id}"
                    class="text-xs text-red-400 hover:text-red-300">Delete</button>
            </div>
        </div>`).join('') || '<p class="text-gray-500 text-sm">No roles yet.</p>';
}

async function loadActivity() {
    const data = await staffFetch('/activity/');
    document.getElementById('staffActivityList').innerHTML = data.results.map(entry => `
        <div class="bg-dark-card border border-dark-border rounded-lg px-4 py-3 flex justify-between items-center gap-4">
            <span class="text-sm text-gray-300">${escapeHtml(entry.summary)}</span>
            <span class="text-xs text-gray-600 whitespace-nowrap">
                ${escapeHtml(new Date(entry.created_at).toLocaleString())}
            </span>
        </div>`).join('') || '<p class="text-gray-500 text-sm">Nothing yet.</p>';
}

function capabilityCheckboxes(selected) {
    return CAPABILITY_GROUPS.map(group => `
        <div class="mb-4">
            <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                ${escapeHtml(group.label)}
            </div>
            ${group.capabilities.map(cap => `
                <label class="flex items-center gap-2 py-1 text-sm text-gray-300">
                    <input type="checkbox" value="${escapeHtml(cap.codename)}"
                        ${selected.includes(cap.codename) ? 'checked' : ''}
                        class="capability-box rounded bg-[#06090F] border-dark-border">
                    ${escapeHtml(cap.label)}
                </label>`).join('')}
        </div>`).join('');
}

function openStaffModal(title, bodyHtml) {
    document.getElementById('staffModalTitle').textContent = title;
    document.getElementById('staffModalBody').innerHTML = bodyHtml;
    const modal = document.getElementById('staffModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeStaffModal() {
    const modal = document.getElementById('staffModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.getElementById('staffModalBody').innerHTML = '';
}

function selectedCapabilities() {
    return Array.from(document.querySelectorAll('.capability-box:checked')).map(b => b.value);
}

function selectedRoleIds() {
    return Array.from(document.querySelectorAll('.role-box:checked')).map(b => Number(b.value));
}

function roleCheckboxes(selectedNames) {
    return ROLES.map(role => `
        <label class="flex items-center gap-2 py-1 text-sm text-gray-300">
            <input type="checkbox" value="${role.id}"
                ${selectedNames.includes(role.name) ? 'checked' : ''}
                class="role-box rounded bg-[#06090F] border-dark-border">
            ${escapeHtml(role.name)}
        </label>`).join('');
}

document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('staff');
    if (!section) return;   // user lacks manage_staff; the section was not rendered

    document.getElementById('staffModalClose').addEventListener('click', closeStaffModal);

    section.querySelectorAll('.staff-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            section.querySelectorAll('.staff-tab').forEach(t => {
                t.classList.remove('text-white', 'border-brand-blue');
                t.classList.add('text-gray-400', 'border-transparent');
            });
            tab.classList.add('text-white', 'border-brand-blue');
            tab.classList.remove('text-gray-400', 'border-transparent');

            section.querySelectorAll('.staff-pane').forEach(p => p.classList.add('hidden'));
            const paneId = { people: 'staffPeople', roles: 'staffRoles', activity: 'staffActivity' }[tab.dataset.tab];
            document.getElementById(paneId).classList.remove('hidden');
        });
    });

    document.getElementById('inviteBtn').addEventListener('click', () => {
        openStaffModal('Invite person', `
            <div class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-400 mb-2">Email address</label>
                    <input type="email" id="inviteEmail" required
                        class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-400 mb-2">Roles</label>
                    ${roleCheckboxes([])}
                </div>
                <button type="button" id="sendInviteBtn"
                    class="w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg">
                    Send invitation
                </button>
            </div>`);

        document.getElementById('sendInviteBtn').addEventListener('click', async () => {
            const email = document.getElementById('inviteEmail').value.trim();
            if (!email) { alert('Enter an email address.'); return; }
            try {
                await staffFetch('/invitations/', {
                    method: 'POST',
                    body: JSON.stringify({ email, role_ids: selectedRoleIds() }),
                });
                closeStaffModal();
                await loadPeople();
                alert('Invitation sent.');
            } catch (e) { alert(`Could not send the invitation: ${e.message}`); }
        });
    });

    document.getElementById('newRoleBtn').addEventListener('click', () => {
        openStaffModal('New role', `
            <div class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-400 mb-2">Role name</label>
                    <input type="text" id="roleName"
                        class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
                </div>
                <div>${capabilityCheckboxes([])}</div>
                <button type="button" id="saveRoleBtn" data-role-id=""
                    class="w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg">
                    Create role
                </button>
            </div>`);
        wireRoleSave();
    });

    // Delegated handlers: never build JavaScript inside an HTML attribute.
    section.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-action]');
        if (!button) return;
        const id = Number(button.dataset.id);

        if (button.dataset.action === 'revoke-invite') {
            if (!confirm('Revoke this invitation? The link stops working.')) return;
            try {
                await staffFetch(`/invitations/${id}/`, { method: 'DELETE' });
                await loadPeople();
            } catch (e) { alert(`Could not revoke: ${e.message}`); }
        }

        if (button.dataset.action === 'delete-role') {
            const role = ROLES.find(r => r.id === id);
            if (!confirm(`Delete the role "${role ? role.name : ''}"? Members keep their accounts but lose these capabilities.`)) return;
            try {
                await staffFetch(`/roles/${id}/`, { method: 'DELETE' });
                await Promise.all([loadRoles(), loadPeople()]);
            } catch (e) { alert(`Could not delete: ${e.message}`); }
        }

        if (button.dataset.action === 'edit-role') {
            const role = ROLES.find(r => r.id === id);
            if (!role) return;
            openStaffModal(`Edit ${role.name}`, `
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-400 mb-2">Role name</label>
                        <input type="text" id="roleName" value="${escapeHtml(role.name)}"
                            class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
                    </div>
                    <div>${capabilityCheckboxes(role.capabilities)}</div>
                    <button type="button" id="saveRoleBtn" data-role-id="${role.id}"
                        class="w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg">
                        Save changes
                    </button>
                </div>`);
            wireRoleSave();
        }

        if (button.dataset.action === 'edit-person') {
            const people = await staffFetch('/people/');
            const person = people.results.find(p => p.id === id);
            if (!person) return;
            openStaffModal(`Edit ${person.username}`, `
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-400 mb-2">Roles</label>
                        ${roleCheckboxes(person.roles)}
                    </div>
                    <label class="flex items-center gap-2 text-sm text-gray-300">
                        <input type="checkbox" id="personActive" ${person.is_active ? 'checked' : ''}
                            class="rounded bg-[#06090F] border-dark-border">
                        Account active
                    </label>
                    <button type="button" id="savePersonBtn" data-person-id="${person.id}"
                        class="w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg">
                        Save changes
                    </button>
                </div>`);

            document.getElementById('savePersonBtn').addEventListener('click', async () => {
                try {
                    await staffFetch(`/people/${id}/`, {
                        method: 'PATCH',
                        body: JSON.stringify({
                            role_ids: selectedRoleIds(),
                            is_active: document.getElementById('personActive').checked,
                        }),
                    });
                    closeStaffModal();
                    await Promise.all([loadPeople(), loadRoles()]);
                } catch (e) { alert(`Could not save: ${e.message}`); }
            });
        }
    });
});

function wireRoleSave() {
    document.getElementById('saveRoleBtn').addEventListener('click', async (event) => {
        const roleId = event.currentTarget.dataset.roleId;
        const name = document.getElementById('roleName').value.trim();
        if (!name) { alert('Give the role a name.'); return; }
        const payload = JSON.stringify({ name, capabilities: selectedCapabilities() });
        try {
            if (roleId) {
                await staffFetch(`/roles/${roleId}/`, { method: 'PUT', body: payload });
            } else {
                await staffFetch('/roles/', { method: 'POST', body: payload });
            }
            closeStaffModal();
            await Promise.all([loadRoles(), loadPeople()]);
        } catch (e) { alert(`Could not save the role: ${e.message}`); }
    });
}
```

- [ ] **Step 9: Reflect the send capability on campaign cards**

In `brand/static/brand/js/admin/campaigns.js`, find where the queue/send button is rendered for a draft campaign. Wrap it so a user without `send_campaigns` sees the reason rather than a missing control:

```javascript
${window.can('send_campaigns')
    ? `<button type="button" data-action="queue-campaign" data-campaign-id="${c.id}"
            class="text-xs px-3 py-1 rounded bg-brand-green text-black font-semibold">Send</button>`
    : `<span class="text-xs text-gray-500 italic">Awaiting an administrator to send</span>`}
```

Match the surrounding code's existing button markup and event wiring; the point is the conditional, not this exact styling.

- [ ] **Step 10: Run the tests to verify they pass**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff --keepdb
```

Expected: OK.

- [ ] **Step 11: Run everything**

```bash
cd brandtechsolution && .venv/bin/python manage.py test staff messaging appointments brand.test_api_permissions brand.test_blog_status --keepdb
```

Expected: OK. Then confirm the pre-existing baseline is unmoved:

```bash
cd brandtechsolution && .venv/bin/python manage.py test brand.tests --keepdb 2>&1 | tail -3
```

Expected: `FAILED (failures=7, errors=17)`.

- [ ] **Step 12: Commit**

```bash
git add brandtechsolution/brand brandtechsolution/staff
git commit -m "feat(staff): add the Staff & Roles panel section"
```

---

## Task 13: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the feature**

Add a "Staff roles and permissions" section to `README.md` covering:

- The eleven capabilities and what each one gates, as a table.
- The four preset roles and their capabilities, noting that `send_campaigns` is withheld from Marketing by default and can be granted from the Roles tab.
- How to invite someone: Staff & Roles → Invite person → email plus roles; the invitee sets their own password; links expire after 7 days.
- That superusers bypass every capability check, and that a non-superuser cannot edit their own roles or deactivate themselves.
- That the audit log is append-only and visible under Staff & Roles → Activity.
- Blog posts are now created as drafts and need `publish_blog` to go live.

- [ ] **Step 2: Note the deployment requirements**

Add to the deployment notes:

```markdown
This release adds migrations for the new `staff` app and a `status` field on
`BlogPost`. Run `python manage.py migrate` on deploy. The blog migration
backfills every existing post to `published`, so nothing disappears from the
public site. No new Python dependencies are added, so a plain container
restart is sufficient once migrations have run.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document staff roles, capabilities and invitations"
```

---

## Self-Review Notes

Checked against the spec:

- **Capability list, storage, registry** — Task 1.
- **Preset roles, sending withheld from Marketing** — Task 2.
- **Enforcement primitives** — Task 3.
- **Enforcement map** — Tasks 4 (messaging), 5 (brand), 7 (appointments); the `staff` app's own endpoints self-gate on `manage_staff` in Tasks 9-11.
- **Duplicate routing and `/api/events/` removal** — Task 5.
- **Blog draft state with backfill** — Task 6.
- **Audit log, append-only, summary rendered at write time** — Task 8.
- **Roles API** — Task 9. **People API and self-lockout** — Task 10. **Invitations** — Task 11.
- **UI, nav gating, `window.CAPABILITIES`, send-button state** — Task 12.
- **Documentation** — Task 13.

Known ordering constraint: Task 2's data migration must create permission rows itself, because `post_migrate` has not run when migrations execute on a fresh database. Step 5 of that task tests exactly this.
