# GitHub database cache plan

- [x] Add persistent repository snapshots and scoped refresh state models/migration.
- [x] Persist discovery/account data; overlay live local Project fields on cached repository rows.
- [x] Share persistent document/roadmap, README and commit caches across GitHub sync and task imports.
- [x] Add coalesced background refreshes, retry/backoff and revision-aware skips.
- [x] Serve GET endpoints from the database; protect POST refreshes and update freshness/pending UI.
- [x] Invalidate affected snapshots on verified pushes and integrate scheduled refresh.
- [x] Add request-count, persistence, authorization and failure regression tests.
- [x] Run app checks/browser validation, warm local data, and update README/changelog/roadmap.


## Validation

- 382 affected task/staff/GitHub/document tests passed. After the final memory-cache credential boundary change, all 54 cache/document regression tests passed, including the additional credential-isolation case.
- Full brand/tasks/staff run: 654 tests, with exactly the same 32 failures/errors as the isolated unchanged baseline (13 failures, 19 errors, two skips); no additional failing test names.
- Migration consistency reports no changes. Applied `brand.0022_github_database_cache` and `tasks.0005_github_processed_revision` to the local development PostgreSQL database.
- Warmed 11 repository snapshots and account details through the background-refresh implementation.
- Authenticated Playwright checks passed for the real saved list/account, README and commit inspector, POST refresh wiring, desktop/mobile layout and absence of browser JavaScript errors. Manual refresh POST was intercepted during browser validation to avoid redundant GitHub requests.
- Three saved-list reads measured 74 ms, 112 ms and 106 ms locally (27,762 bytes before response compression). These are local development observations, not production latency guarantees.
- Request-count tests prove warm GETs do not construct a GitHub client, unchanged revisions skip payload downloads, document hashes reuse unchanged text, negative results persist and rate-limit backoff suppresses further upstream work.
- JavaScript syntax and `git diff --check` passed.
