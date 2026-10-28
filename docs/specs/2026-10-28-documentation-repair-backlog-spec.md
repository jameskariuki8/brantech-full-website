# Documentation repair backlog

Synced GitHub projects automatically create unassigned repair work for missing or invalid README.md, CHANGELOG.md, ROADMAP.md and LICENSE files, using the same audit as GitHub Manager. The existing Roadmap backlog is renamed Project backlog because it contains both roadmap work and documentation repairs.

Create one active repair task per repository and required document. Its description includes every current finding and repair instruction for that document. Repeated audits update findings without duplicating tasks or changing assignees. A missing roadmap must not prevent documentation repair work being imported. Failed/unknown audits must not create missing-document claims or resolve existing findings.

When an audit confirms a document is healthy, mark its repair task resolved. Unassigned resolved tasks leave the backlog; assigned tasks submit for review through the existing workflow, never auto-approve. A new failure after approval creates a fresh repair task. If an unapproved issue recurs, reuse the active task and make it available again if unassigned. Reviewers can still reject work and request rework.

Backlog rows identify documentation repairs, project and affected document. The existing search, project filters and capability-protected assignment action work for both task sources. Pushes changing any of the four documents queue an audit on the default branch; polling remains the fallback. No new permissions or automatic assignments.

Tests cover all four missing files, multiple findings per file, idempotence, updated findings, resolution and review, recurrence after approval, unknown audits, empty repositories, docs-only webhook pushes and mixed backlog/API behavior.
