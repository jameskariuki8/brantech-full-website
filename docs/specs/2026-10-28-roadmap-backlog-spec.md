# Automatic project backlog

Documentation repairs extend this flow: see [the documentation repair specification](2026-10-28-documentation-repair-backlog-spec.md). The workspace is now labelled Project backlog.

## User flow

The existing GitHub-synced Project list is the source of repositories. Users must not copy repository names into the Tasks page. Each scheduled task sync discovers these projects and imports their roadmap leaf items into an unassigned backlog. A successful project sync also queues its task import. No import chooses assignees; the existing recommendation algorithm is dormant until a separately authorized assignment policy is implemented.

Tasks has two workspaces: Assigned work and Roadmap backlog. The assigned board excludes unassigned roadmap tasks. The backlog uses compact rows with task title, project, milestone/context, priority and an Assign action; it supports search, project filtering, pagination, loading, empty and error states. A small import status line replaces the repository configuration card. Project names come from Project.title, with repository names as a fallback for legacy links.

A task manager can select one or more active staff in an assignment dialog. A capability-protected, row-locked assignment action accepts only assignee IDs, preserves existing completion state and records activity. Another manager assigning the same backlog task first produces a conflict rather than silently replacing their selection. Existing assignees are never removed by import. Future authenticated automation may use the same capability-protected action, but is not implemented here.

Imports remain idempotent. Checked roadmap items that were never assigned leave the available backlog without marking the task approved or changing existing assignments. They reappear if unchecked. Linked commit completion and administrator review remain intact.

## Delivery

Add a nullable project link to the internal Repository record, discover links from synced projects, queue imports after project sync, remove import-time assignment, add backlog APIs and implement the workspace UI. Reuse current templates, Tailwind, Font Awesome and modal conventions. Do not add a frontend framework or dependencies.

## Verification

Cover project discovery and import idempotence, no automatic assignments, assigned/backlog filtering, project metadata, completed roadmap visibility, assignment permission/validation/conflicts, project-sync enqueue behavior and template gating. Run affected tasks, staff and brand tests and inspect the desktop/mobile layout in a browser if available.
