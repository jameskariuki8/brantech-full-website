# Staff scope in onboarding and profile

## Problem
Onboarding and the profile form only describe engineers: role choices, languages, frameworks and GitHub. Staff in marketing, sales or operations have nothing to say about what they do, and the team cannot tell who to ask about what.

## Decisions
- **Scope** is a list of business areas on `StaffProfile.scopes` (JSON list of strings). Suggested values live in `staff/profile_options.py` (`SCOPE_CHOICES`); people may add their own. Values are trimmed, de-duplicated case-insensitively and sorted by `clean_list`.
- **Required at onboarding**: at least one scope, after the phone checks. Accounts onboarded before this change are not re-prompted; their scopes are empty until they edit their profile.
- **Role list** gains non-engineering titles. The onboarding select keeps a stored custom value as an option so it is never lost.
- **Technical skills** (languages, frameworks, GitHub) stay on the page but sit in a `<details>` that is open when the person has data or ticks Engineering / Product & Design. The form works with it closed.
- **Dashboard**: the My profile form edits scopes (pills plus a custom field), role (free text with suggestions), bio, and the existing fields. The suggestions come from `GET /api/staff/me/` as `options`, so there is one list.
- **Roster**: `scopes` is read-only in `GET /api/staff/people/`; only the owner of a profile changes it. Shown in the row and editor and included in search.

## Not in scope
Administrators editing someone else's scope or skills; filtering the roster by scope; using scope to route tasks.

## Deploy
Run `migrate` (`staff.0019`).
