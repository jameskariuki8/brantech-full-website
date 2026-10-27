# Custom staff groups

Date: 2026-10-27
Branch: `feat/custom-staff-groups`

## Problem

An administrator should be able to create a staff group, decide what it may do, and put people in it, all from the panel. Today:

- **Shared mailboxes are hardcoded.** `SHARED_MAILBOXES` in `staff/handles.py` fixes the list (info, hello, support, careers, jobs, hr, sales, billing, contact). A new team address needs a code change.
- **Mailbox access is all or nothing.** `view_inbox` reads every shared mailbox, so an HR group cannot be given hr@ and careers@ without also reading sales@ and billing@.
- **Membership is managed from the person, not the group.** A role (Django `auth.Group`) can be created with capabilities, but people are added one at a time from their own editor. There is no way to see a group, add people to it, or invite someone straight into it.

## Design

A group is the existing `auth.Group`. The panel calls it a "group" instead of a "role"; the API keeps its `/api/staff/roles/` path.

A group holds:

1. **Capabilities**: unchanged.
2. **Shared mailboxes**: new. Members read and reply from them.
3. **Members**: existing staff, added or removed from the group editor.
4. **Invitations**: emails invited into the group from the group editor. They join it when they accept.

### Shared mailboxes become data

- `messaging.SharedMailbox(name unique, groups M2M auth.Group related_name="shared_mailboxes", created_by, created_at)`.
- A data migration seeds the nine current names with no groups, so nothing changes for anyone until a mailbox is linked to a group.
- Names follow the handle rules (lowercase letters, digits, dots, hyphens), 2 to 30 characters. A name must not belong to a staff member, and must not be a system address (postmaster, abuse, mailer-daemon, no-reply, other, ...).
- Deleting a mailbox moves its conversations to Unmatched. New mail to that address also lands there.
- A personal handle cannot be the name of a shared mailbox.
- Managed under `/api/messaging/mail/shared/` by `manage_staff` holders, and audited (`mailbox_created`, `mailbox_deleted`).

### Access

| Who | Reads | Replies and sends from |
|---|---|---|
| Member of a group linked to mailbox M | M | M |
| `view_inbox` | every shared mailbox and Unmatched | |
| `handle_inquiries` | | every shared mailbox and Unmatched |
| superuser | everything | everything |

Mail arriving in M is also emailed to the members of M's groups, in addition to `receive_inquiry_emails` holders.

Campaigns may still be sent from any shared mailbox by anyone holding `manage_campaigns`, as now.

### Granting stays bounded

A person without `manage_staff` has no say. A `manage_staff` holder who is not a superuser:

- may only add a capability or a mailbox to a group if they hold it themselves. For a mailbox, "holding it" means being able to send from it.
- may only add someone to a group (or invite them into it) if they hold everything the group grants. `enforce_grantable_roles` now also checks the group's mailboxes.
- may not change their own groups, or a superuser's groups. This matches the existing person editor.

Removing anything is never restricted.

### API

- `GET/POST/PUT/DELETE /api/staff/roles/`: the representation gains `mailboxes` (names), `members` (`[{id, name, username}]`) and `invited` (pending invitation emails). Writes accept `mailboxes` and `member_ids`. Membership changes are diffed and audited per person (`roles_changed`).
- Invitations into a group use the existing `POST /api/staff/invitations/` with `role_ids`.
- `GET/POST /api/messaging/mail/shared/`, `DELETE /api/messaging/mail/shared/<name>/`.

### UI (Staff & Groups)

- The tab and buttons say "Groups".
- Each group card lists its members, mailboxes and capabilities.
- The group editor has these sections: name; members (tick staff, with locked rows explained); invite by email (one per line, sent after saving); shared mailboxes (tick, or create a new one inline); capabilities.
- A "Shared mailboxes" list in the Groups tab shows each mailbox, the groups that use it, and a delete button.

## Out of scope

- Separate read-only and reply access per group mailbox. A group's mailboxes are read and reply.
- Renaming a mailbox. Delete and recreate it instead; delete refiles its mail to Unmatched.

## Tests

- `messaging/tests/test_shared_mailboxes.py`: seeding; create/delete rules; routing to a new mailbox; group members read and reply only their group's mailboxes; `view_inbox`/`handle_inquiries` keep their reach; notifications reach group members; deletion refiles to Unmatched; handle validation refuses a mailbox name.
- `staff/tests/test_group_members.py`: members and mailboxes on the role API; escalation checks for capabilities, mailboxes and members; self and superuser locks; audit entries; invitations into a group.
