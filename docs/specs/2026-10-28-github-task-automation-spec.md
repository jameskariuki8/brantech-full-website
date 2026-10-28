# GitHub task automation specification

> The original repository-linking and automatic-assignment UX below is superseded by [the roadmap backlog specification](../specs/2026-10-28-roadmap-backlog-spec.md). Current behavior imports existing synced projects into an unassigned backlog; managers assign the work.

Linked GitHub repositories feed the native task board without creating public Project records. Only `manage_tasks` holders may manage repository links, request a sync, or approve work. Staff managers may disable automatic assignment in the person editor; manual assignment is unaffected.

Commit messages naming `Task #N` appear on that task, including author, merge state and a safe GitHub link. Closing messages and task-branch merges submit assigned tasks for review only on the default branch. Duplicate deliveries do not duplicate activity or resubmit reopened work. Commits from a different linked repository must not finish a task already associated with another repository.

Unchecked leaf roadmap items in unfinished milestones create tasks. Existing unlinked manual tasks with matching titles are reused. Newly checked items submit assigned tasks for review. Persist checkbox state so unchanged checked items cannot override an administrator sending work back; unticking then reticking permits resubmission. Assignment ranks eligible active onboarded developers by role area, skill matches, unfinished workload and username. Paused staff and staff without technical skills are excluded.

Celery Beat polls every `BEAT_TASK_REPO_INTERVAL` seconds (default 600), with the configured `GITHUB_ACCESS_TOKEN`. An optional push webhook verifies `GITHUB_WEBHOOK_SECRET` before processing. GitHub failures remain visible and must not advance the polling cursor. Concurrent roadmap reads must not create duplicates.

The Tasks screen provides repository linking, roadmap toggles, manual checks, unlinking, sync errors and commit details. `link_repo owner/name` provides equivalent command-line setup; `--check` explicitly performs a sync. No repository is linked automatically by deployment.

Validation uses mocked GitHub clients and signed webhook requests, plus the tasks and staff suites. Live credentials, production writes and webhook registration are outside local verification.
