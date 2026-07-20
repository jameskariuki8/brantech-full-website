# Staff Roles and Permissions — Design

**Date:** 2026-07-21
**Status:** Approved for planning

## Goal

Replace the panel's single binary `is_staff` gate with named roles, so a
teammate can be given exactly the access their job needs — and so drafting a
campaign can be separated from sending one.

## Problem

Access control today is all-or-nothing. `brand/views.py:15` admits anyone with
`is_staff or is_superuser`, and every messaging endpoint uses DRF's
`IsAdminUser`, which is the same check. Any staff account can publish blog
posts, read the contact inbox, and mail the entire contact list.

Django's `Group` and `Permission` tables are unused: nothing imports them and
there is no `has_perm()` call in the codebase.

The database has one user, a superuser, and no groups. There are no existing
staff accounts to migrate, and superusers bypass `has_perm()` unconditionally,
so the existing account cannot be locked out by this work.

### Related fix already shipped

Commit `49d31d8` (merged as `32ae90d`) closed two unauthenticated write paths
found while scoping this design: `/api/events/` was an `AllowAny` viewset, and
the blog/project write endpoints checked `is_authenticated` rather than
`is_staff` while `/signup/` is public. That fix is a stopgap using `is_staff`;
this design replaces those checks with capability checks.

## Decisions

| Question | Decision |
|---|---|
| Permission model | Django `Group` as the role; custom capability permissions |
| Granularity | 11 curated capabilities, not auto-generated CRUD permissions |
| Onboarding | Invitation by email; the invitee sets their own password |
| Starter roles | 4 presets shipped via data migration, freely editable |
| Audit | Role and account changes recorded, viewable in the panel |
| Appointments | In scope |
| Blog draft state | Added, so "Publish blog posts" gates a real transition |

## The capability list

Eleven capabilities, grouped as they appear in the UI:

**Content**
- `manage_blog` — Manage blog posts
- `publish_blog` — Publish blog posts
- `manage_projects` — Manage projects
- `manage_appointments` — Manage appointments

**Communications**
- `view_inbox` — View inbox
- `handle_inquiries` — Reply to and archive inquiries
- `manage_templates` — Manage email templates
- `manage_campaigns` — Create and edit campaigns
- `manage_recipients` — Manage campaign recipients
- `send_campaigns` — Send campaigns

**Administration**
- `manage_staff` — Manage staff and roles

### Storage

Django permissions must attach to a model. Rather than scatter these across
`BlogPost`, `Campaign` and others — where they would sit among roughly fifty
auto-generated CRUD permissions — they attach to one sentinel model:

```python
class StaffCapability(models.Model):
    """No rows and no table. Exists only to own the panel's permissions."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("manage_blog", "Manage blog posts"),
            # ... the remaining ten
        ]
```

`managed = False` means no table is created; `default_permissions = ()`
suppresses the automatic add/change/delete/view set. Django's `post_migrate`
hook still creates the `auth_permission` rows, so these are ordinary
permissions — `Group`, `user.has_perm()` and Django's own `/admin/` all work
unmodified. Codenames read as `staff.send_campaigns`.

`staff/capabilities.py` holds the registry that feeds `Meta.permissions`, the
API's capability-list endpoint and the UI checkboxes, so the three cannot
drift. This mirrors the placeholder registry already used in `messaging`.

## Preset roles

Created by data migration as ordinary groups. They may be renamed, edited or
deleted.

| Role | Capabilities |
|---|---|
| Editor | `manage_blog`, `publish_blog`, `manage_projects` |
| Marketing | `manage_templates`, `manage_campaigns`, `manage_recipients`, `send_campaigns` |
| Support | `view_inbox`, `handle_inquiries`, `manage_appointments` |
| Administrator | All eleven |

## Architecture

A new `staff` app alongside `brand`, `messaging` and `appointments`:

```
staff/
  capabilities.py   registry: single source of truth for the capability list
  models.py         StaffCapability, StaffInvitation, AuditEntry
  permissions.py    HasCapability — DRF permission class
  decorators.py     capability_required — for plain Django views
  api.py            groups, staff users, invitations, audit log
  serializers.py
  emails.py         invitation delivery
  audit.py          record() helper
  urls.py, api_urls.py
```

Enforcement is one DRF permission class plus one decorator, applied across the
existing apps. Everything else is self-contained in `staff`.

## Enforcement map

| Endpoint | Capability |
|---|---|
| `/api/posts/` writes (and `/api/posts.json`) | `manage_blog` |
| Blog draft → published transition | `publish_blog` |
| `/api/projects/` writes | `manage_projects` |
| `/api/events/` writes | `manage_projects` |
| Messaging inquiries, read | `view_inbox` |
| Messaging inquiries, write | `handle_inquiries` |
| Messaging templates | `manage_templates` |
| Campaign CRUD | `manage_campaigns` |
| Campaign `send`, `pause`, `resume` | `send_campaigns` |
| Campaign recipients | `manage_recipients` |
| Appointments staff views | `manage_appointments` |
| Everything under `staff` | `manage_staff` |

Reads on the public content APIs stay open to anonymous visitors — the blog and
projects pages depend on them.

Nav items hide when a capability is absent, but hiding is cosmetic. The API
check is the gate, and each endpoint gets a test asserting 403 without the
capability.

### Duplicate routing

`/api/posts/` and `/api/projects/` are implemented twice: function views in
`brand/api_views.py` and router viewsets in `brand/api.py`. The function views
shadow the router only on `<int:pk>` paths, which is how `/api/posts.json`
reached an unprotected viewset. The implementation must settle on one and
delete the other rather than gate both.

`/api/events/` has no consumer anywhere in the templates or JavaScript, and the
panel has no Events section. It is mapped to `manage_projects` above so that it
is not left ungated, but deleting the route and its viewset is the better
outcome. The implementation should confirm nothing external depends on it and
then remove it; if it is removed, `manage_projects` simply stops applying
there.

## Invitations

```
admin POST /api/staff/invitations/ {email, group_ids}
  -> StaffInvitation row created; no User yet
  -> token = signing.dumps({"id": inv.id}, salt="staff.invite")
  -> send_mail with a link to /staff/invite/<token>/

invitee opens the link
  -> set-password form
  -> User(is_staff=True) created, password set, groups applied,
     accepted_at stamped
```

This follows `messaging/tokens.py`, which already signs values with a salt, and
`messaging/views.py:86`, which already sends transactional mail with
`send_mail`. Invitations are transactional and must not queue behind a
campaign, so they do not use the outbox.

- **Expiry:** 7 days, enforced by `signing.loads(max_age=...)`.
- **Username:** the email address. Django's username validator permits
  `@ . + - _`, so the invitee makes one decision rather than two.
- **Single use:** acceptance is a guarded update —
  `filter(pk=..., accepted_at__isnull=True).update(accepted_at=now)` — and
  proceeds only if one row was affected. This is the pattern the outbox already
  uses for claiming rows, and it stops two people opening the same link from
  both creating an account.
- **Resend:** issues a fresh token and resets expiry on the same invitation.
- **Revoke:** deletes the row, which invalidates the link.
- **Existing email:** refused with a message directing the admin to edit that
  user's roles instead. No duplicate account is created.

## Audit log

`AuditEntry` is append-only: no update or delete path exists in the API.

Fields: `actor` (FK, `SET_NULL`), `action`, `target_user` (nullable),
`target_group` (nullable), `detail` (JSON before/after of the capability set),
`summary`, `created_at`.

`summary` is rendered at write time so an entry still reads correctly after the
user or group it refers to has been deleted.

Entries are written by `staff.audit.record()` inside the same transaction as
the change they describe. Actions covered: invite sent, invite revoked, invite
accepted, roles changed, account deactivated, account reactivated, group
created, group renamed, group deleted.

## Blog draft state

`BlogPost` currently has no draft or published state — creating a post
publishes it, since the public blog page lists `BlogPost.objects.all()`. Without
a draft state, `publish_blog` would gate nothing.

- Add `status` to `BlogPost` with choices `draft` and `published`, defaulting to
  `draft` for new rows.
- **The migration must backfill every existing row to `published`.** A plain
  default would empty the live blog on deploy.
- The public blog list and detail views filter to `published`.
- Moving a post from `draft` to `published` requires **both** `manage_blog` and
  `publish_blog`. `publish_blog` alone grants nothing; it is a modifier on blog
  management, not a standalone capability. All other edits require `manage_blog`
  only.

## UI

One nav section, **Staff & Roles**, visible only with `manage_staff`, in three
tabs:

- **People** — staff list with role chips and status (active, invited,
  deactivated). Invite, change roles, deactivate, resend invitation.
  Lists users with `is_staff=True` plus pending invitations. Ordinary accounts
  created through the public `/signup/` page are not staff and never appear
  here; the only route into this list is an accepted invitation.
- **Roles** — groups with member counts. Create, rename, delete. Editing opens
  the capability checkboxes grouped Content / Communications / Administration.
- **Activity** — the audit log, paginated.

Files follow the existing panel convention:
`brand/templates/brand/admin/_staff.html` and
`brand/static/brand/js/admin/staff.js`.

Nav gating is server-rendered from the user's capability set. A
`window.CAPABILITIES` block exposes the same set to JavaScript so buttons can be
hidden. Every value rendered into the panel passes through `escapeHtml()`.

## Safety rails

- Superusers bypass every capability check. The existing account cannot be
  locked out.
- A non-superuser cannot edit their own roles or deactivate their own account
  (403). This is one simple rule rather than fragile last-admin-standing
  arithmetic; superusers remain the escape hatch.
- Deactivation sets `is_active=False`.
- Preset roles are ordinary groups with no special protection.

## Testing

- Every gated endpoint: 403 without the capability, success with it.
- Invitations: happy path, expired token, reused token, revoked token, and two
  concurrent acceptances of the same token.
- An audit entry is written for each recorded action, and the summary survives
  deletion of its target.
- Self-lockout rules: self role edit and self deactivation both refused.
- Preset roles exist after migration with the expected capabilities.
- The public blog lists only published posts, and existing posts are published
  after the backfill migration.
- No test performs real network access.

## Out of scope

- Object-level permissions (e.g. "may edit only their own posts").
- Two-factor authentication and password policy.
- Self-service password reset — Django's built-in views are already routed at
  `/accounts/`.
- Per-role rate limits.

## Open risk

The panel has never been exercised in a real browser; there is no JavaScript
test harness in the repository, so all UI behaviour is verified by inspection
only. This feature adds a third modal-driven section, which increases the value
of a manual click-through before release.
