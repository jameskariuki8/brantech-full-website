# Persistent GitHub cache

## Problem and behavior

GitHub Manager currently enumerates repositories and account details on every visit, previews unimported READMEs live, and repeats document/roadmap reads during task polling. Empty results are treated as cache misses. The database must be the normal read source across web and worker restarts.

Persist account information, repository metadata, document findings and roadmap text, README content (including known absence), recent commits (including an empty list), and refresh status. Cache scope is a hash of the configured GitHub credential/account: credentials are never stored, and changing credentials must not expose a previous account's cached private repositories. Render local Project fields from current database rows so CMS edits remain current.

Ordinary list/account/README/commit GETs make no GitHub calls. Missing or stale data queues a background refresh and immediately returns cached data with freshness/pending status. Only capability-protected POSTs request manual refresh; the public commit endpoint cannot consume GitHub quota with a query-string refresh. Failed refreshes preserve last-good data, publish generic errors, and respect GitHub rate-limit reset/retry headers. Coalesce concurrent requests with a database refresh lease and bounded retry delay. Expired leases are recoverable.

The existing hourly GitHub job refreshes discovery/account metadata and tracked projects. Repository pushes invalidate/refresh the affected repository only. Push timestamp and default branch identify content revisions, and document hashes avoid re-downloading unchanged text; unchanged revisions reuse saved documents, README and commits. A bounded freshness interval allows recovery from missed webhooks, force-pushes and metadata changes. Task polling checks repository metadata and skips commit/document/roadmap downloads when the same revision was successfully processed; document text and audits are shared with GitHub Manager.

Discovery snapshots do not create public Projects. Repository access lost on a confirmed 403/404 must not be served as current; failed discovery must not delete otherwise valid stale results. Staff repository mapping is refreshed with discovery, and project edits/imports are overlaid at read time. No new frontend dependency.

## Validation

Use mocked GitHub clients to assert zero upstream calls on warm GETs, correct negative caching, reuse across cache/backend resets and service instances, revision-triggered invalidation, unchanged polling skips, local project edit visibility, scoped credentials, refresh authorization, coalescing, rate-limit backoff and last-good-data preservation. Run affected task/staff/GitHub/document suites, migrations and browser checks. Existing unrelated brand-suite failures remain outside this change.
