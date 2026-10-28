# Documentation repair backlog plan

- [x] Add documentation source and resolution state with a migration.
- [x] Reuse GitHub Manager document audits during imports; create/update repair work per document.
- [x] Handle resolution, recurrence, failed audits and empty repositories without bypassing review.
- [x] Include documentation work in backlog filters, counts and assignment.
- [x] Refresh backlog labels and row context; re-audit on document pushes.
- [x] Test affected apps and document-check integration, migrate/restart dev and verify real import.
- [x] Update README, changelog and roadmap.


## Validation

- 359 tests passed across tasks, staff, GitHub integration and shared document checks (SQLite; test-only MD5 password hashing).
- After the webhook response refinement, all 17 documentation and webhook regression tests passed.
- Migration consistency: no changes detected. `tasks.0004_documentation_repair` applied to the local PostgreSQL development database.
- Live import created seven unassigned documentation repairs across two synced projects.
- Authenticated browser checks verified the seven real repair rows, issue details with fix instructions, assignment dialog, desktop/mobile layouts and absence of JavaScript errors or horizontal overflow. No assignments were changed by browser validation.
- JavaScript syntax and `git diff --check` passed.
