# Staff Onboarding Flow: Coding Capabilities & WhatsApp Integration — Specification

**Date:** 2026-10-09  
**Status:** Draft / Ready for Implementation  
**Affected Apps:** `brandtechsolution/staff`, `brandtechsolution/brand`

---

## 🎯 1. Goal & Objectives

Create a mandatory, streamlined onboarding flow for all staff members upon first login or invitation acceptance to:
1. **Capture Coding & Technical Capabilities**: Inventory each team member's engineering skills (languages, frameworks, primary specialties like Backend, Frontend, AI/ML, DevOps) to optimize task assignment and collaboration.
2. **Collect & Validate WhatsApp Number**: Obtain a verified WhatsApp contact number (formatted strictly in E.164 format, e.g. `+254712345678`) to enable instant team collaboration and platform notifications.
3. **Track Onboarding Completion State**: Ensure users who haven't completed their onboarding are smoothly guided to complete it before navigating unrestricted admin panel sections.

---

## 🏗️ 2. Architectural Design & Data Model Changes

### 2.1 `StaffProfile` Model Enhancements (`brandtechsolution/staff/models.py`)

Extend `StaffProfile` with technical capability fields:

```python
class StaffProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile"
    )
    phone = models.CharField(
        max_length=16,
        blank=True,
        help_text="E.164, e.g. +254712345678. A WhatsApp number is required.",
    )
    daily_mail_limit = models.PositiveIntegerField(null=True, blank=True)

    # NEW: Coding capabilities & engineering profile
    primary_role = models.CharField(
        max_length=64,
        blank=True,
        help_text="e.g. Fullstack Engineer, AI / ML Engineer, Frontend Specialist, DevOps",
    )
    coding_languages = models.JSONField(
        default=list,
        blank=True,
        help_text="List of languages, e.g. ['Python', 'JavaScript', 'TypeScript', 'Rust']",
    )
    frameworks = models.JSONField(
        default=list,
        blank=True,
        help_text="List of frameworks, e.g. ['Django', 'React', 'Next.js', 'TailwindCSS', 'PyTorch']",
    )
    github_username = models.CharField(max_length=100, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    
    # Onboarding status flag
    is_onboarded = models.BooleanField(
        default=False,
        help_text="True when user has completed capabilities and WhatsApp setup.",
    )
    
    updated_at = models.DateTimeField(auto_now=True)
```

---

## 📱 3. WhatsApp Formatting & Validation

* Utilize the existing `staff/phone.py` utility for E.164 normalization:
  - Strips leading zeros, spaces, hyphens, and parenthesis.
  - Prepends country code (default `+254` for Kenyan local numbers `07...` or `01...`).
  - Rejects malformed strings with an actionable validation error.

---

## 💻 4. User Experience & UI Flow

### Step 1: Trigger / Interception
* When an invited staff member accepts their token (`/staff/accept-invite/<token>/`) or logs in for the first time:
  - If `user.staff_profile.is_onboarded == False`, redirect to `/admin-panel/onboarding/` (or display a non-dismissible modal wizard in the admin panel).

### Step 2: Onboarding Step 1 — Personal & WhatsApp Setup
* **WhatsApp Number**: Input with automatic country code prefix selector (`+254`, etc.) and instant format preview (`wa.me/+254...`).
* **Display Name & GitHub Handle**: For repository and team assignment linkage.

### Step 3: Onboarding Step 2 — Coding Capabilities & Stack
* **Primary Role Selector**: Pill selection (Frontend, Backend, Fullstack, AI/Data, DevOps, Mobile).
* **Languages & Frameworks Multi-Select**: Interactive pill badges with search/tagging (Python, Django, JS/TS, React, Tailwind, LangChain/LangGraph, Docker, etc.).
* **Experience Level / Bio**: Brief summary of recent projects or interests.

### Step 4: Completion & Transition
* Saves payload to `StaffProfile`, sets `is_onboarded = True`, logs an `AuditEntry` (`action="onboarding_completed"`), and redirects to the active dashboard.

---

## 🧪 5. Test Suite & Verification Matrix

1. **`StaffProfile` migration test**: Ensure backfill for existing users defaults `is_onboarded=True` or prompts appropriately.
2. **WhatsApp E.164 validation test**: Test valid inputs (`0712345678`, `+254712345678`, `+12025550123`) and invalid inputs (`abc`, `12345`).
3. **Capabilities API test**: Test saving JSON arrays of languages/frameworks via the `/api/staff/me/` endpoint.
4. **Onboarding redirect middleware test**: Verify non-onboarded staff cannot bypass onboarding to access tasks/messaging before completing setup.
