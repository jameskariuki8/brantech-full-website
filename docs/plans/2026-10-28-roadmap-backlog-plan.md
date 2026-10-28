# Roadmap backlog execution plan

- [x] Link internal task repositories to existing GitHub-synced projects and discover them automatically.
- [x] Queue task imports after project sync; keep periodic discovery as recovery.
- [x] Import roadmap work without assigning it; expose backlog/project metadata and filters.
- [x] Add a capability-protected assignment action with concurrency protection.
- [x] Replace manual repository setup with Assigned work / Roadmap backlog workspaces and an assignment dialog.
- [x] Remove active automatic-assignment controls; update feature documentation.
- [x] Run app suites, migration consistency and JavaScript checks; verify the development UI.


## Validation

- Full affected task/staff suites and GitHub integration tests pass (SQLite, test-only MD5 password hashing).
- The broader brand suite has 32 existing failures/errors; an isolated `git archive HEAD` baseline reproduces the identical 32 test names (13 failures, 19 errors).
- Migration consistency: no changes detected. Migration `tasks.0003_repository_project` applied to the local PostgreSQL development database.
- Playwright with Brave verified the authenticated Tasks page, desktop (1440px) and mobile (390px) layouts, assignment validation and submission, absence of the repository linking form and absence of browser JavaScript errors or mobile horizontal overflow. Populated rows and assignment requests used browser-only fixtures; no fake tasks were saved.
- An initial real import reused the existing synced project, completed successfully and found no open roadmap work to add.
- JavaScript syntax and `git diff --check` passed. Ongoing imports require the worker and Beat, provided by Docker Compose.
