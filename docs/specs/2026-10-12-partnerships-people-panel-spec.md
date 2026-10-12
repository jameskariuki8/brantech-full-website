# Partnerships & People in the staff panel

## Problem

The "Partnerships & People" sidebar link opened Django admin in a new tab.
That is a different look, a different navigation, and a page that only
worked for administrators after a permission workaround. The Website Content
page also linked out to Django admin for the same records.

## Scope

A panel page at `/admin-panel/partnerships/` that manages the three models
behind the public `/partnerships/` and `/careers/` pages:

| Tab | Model | Public page |
|-----|-------|-------------|
| Partnership tracks | `PartnershipType` | `/partnerships/` track cards |
| Partners | `PartnerOrganisation` | `/partnerships/` partner strip |
| Job openings | `Career` | `/careers/` |

Each tab lists its records and offers add, edit and delete. Forms are
server-rendered Django forms, the same approach as Website Content, with
file uploads for partner logos and job documents.

## Access

The same rule as Website Content: `can_manage_site_content` (an active
staff account holding Manage staff, or a superuser). Everyone else gets the
themed 403.

## Validation

- Icon: a Font Awesome class such as `fas fa-handshake`.
- Accent: one of blue, amber, emerald, purple, rose.
- Website and logo URL: `http://` or `https://` only.
- Logo upload: an image of at most 2 MB.
- Job document: PDF, DOC or DOCX of at most 10 MB.
- Delete is POST-only and asks for confirmation on the page, without a
  browser dialog.

## Out of scope

- Reordering by drag and drop (the Order number field stays).
- Inbound partnership applications; they arrive by email as before.
- Django admin registrations stay in place as a fallback.
