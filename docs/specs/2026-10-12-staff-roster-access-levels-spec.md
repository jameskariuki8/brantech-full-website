# Staff Roster and Access Levels - Specification

**Date:** 2026-10-12
**Status:** Implemented
**Affected apps:** `brandtechsolution/staff`, `brandtechsolution/brand` (panel UI only)

## Problem

Staff & Roles (`/admin-panel/?section=staff`) did not make it clear who is who.
The person editor showed a bare list of role checkboxes and an "Account active"
box, with the username as its only identity. Nothing said what a role grants,
how roles relate to `is_staff` and `is_superuser`, or why some people could not
be edited. The roster was a flat list with no search or filters.

## Model

Three separate layers, now surfaced in the UI:

| Layer | Where it lives | Meaning |
|---|---|---|
| `is_staff` | User flag | Panel user at all. Every capability check requires it. The roster lists only these accounts. |
| Roles | `auth.Group` | Named bundles of capabilities (Administrator, Editor, Marketing, Support, custom). |
| Capabilities | `staff.*` permissions | What a person can actually do. |
| `is_superuser` | User flag | Bypasses every check. Read-only in the API; only set in `/admin/` or the shell. |

## Access levels

A level is derived on the client from the person's roles and never stored, so
editing a role updates the roster with nothing to remember.

| Level | Rule |
|---|---|
| Owner | `is_superuser` |
| Administrator | holds `manage_staff` through a role |
| Member | holds at least one capability |
| No access | staff account with no capabilities |

Deactivated and Setup pending are shown as status chips alongside the level.

## UI

- **People:** roster with search (name, email, role), filter chips with counts
  (Everyone, Owners, Administrators, Members, No access, Setup pending,
  Deactivated), last sign-in, and a collapsible "How access works" explainer.
  The roster is fetched in full so search and counts are complete.
- **Person editor:** identity and contact header, role cards that say what each
  role grants, a live "What they can do" preview, and the account-active switch
  kept apart from roles. Save stays disabled until something changes.
- **Locked states:** the API forbids editing yourself (unless you are an owner)
  and editing an owner (unless you are one). The editor shows that reason and
  disables the controls instead of failing on save.
- **Roles:** cards show the capabilities each role grants and a link to filter
  the roster to its members.
- **Phones:** modal becomes a bottom sheet; roster rows stack.

## API change

`PersonSerializer` adds read-only `last_login`. No other contract changes; the
rules enforced in `staff/api.py` and `staff/permissions.py` are untouched.

## Out of scope

- Granting or removing `is_superuser` from the panel (deliberately not exposed).
- Showing non-staff accounts or superusers without `is_staff`; the people API
  lists `is_staff=True` only.
- Gating the Django admin (`/admin/`) behind onboarding; only the panel pages (`/admin-panel/`, `/appointments/`, `/editorial/`) are gated.

## Related fix

The onboarding gate now treats a staff account with no `StaffProfile` as not onboarded, and covers superusers without `is_staff`, so every staff member reaches `/staff/onboarding/`. See the Fixed entry in `CHANGELOG.md`.
