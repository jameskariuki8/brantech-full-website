# Editorial Consolidation Plan

Branch: `refactor/editorial-consolidation`
Date: 2026-10-16

## Why

The editorial pipeline was scaffolded as one Django app per "Module N" agent.
Seven of those apps exist only to serve `editorial`, and most of them import
`editorial.models` back, so the boundaries separate nothing:

| App | Code lines | Models | Imported by |
|---|---|---|---|
| `trends` | 718 | TrendTopic, CompetitorSource, CompetitorArticle, TrendPrediction | editorial, research, ai_workflows |
| `research` | 562 | ResearchDossier, VerifiedFactReport | editorial, ai_workflows |
| `approval` | 183 | ApprovalNotification | editorial |
| `publishing` | 173 | PublishingLog | editorial |
| `media_generation` | 157 | MediaAsset | editorial |
| `analytics` | 106 | ContentAnalytics, FeedbackLoopRecord | editorial |
| `seo` | 75 | none | editorial |

The fix is one `editorial` app whose domains are separated by sub-packages,
not by apps.

`knowledge_base` is **out of scope** and stays its own app: it is the pgvector
store (EmbeddingSpace, Embedding, MemoryDocument) that `ai_workflows` uses for
assistant memory and re-embedding, well beyond the newsroom.

## Target layout

```
editorial/
  __init__.py, apps.py, urls.py
  admin/            __init__.py + one module per domain
  models/           __init__.py re-exports every model
    article.py      EditorialArticle
    social.py       SocialPackage
    memory.py       EditorialMemory
    runs.py         EditorialPipelineRun
    trends.py       TrendTopic, CompetitorSource, CompetitorArticle, TrendPrediction
    research.py     ResearchDossier, VerifiedFactReport
    media.py        MediaAsset
    approval.py     ApprovalNotification
    publishing.py   PublishingLog
    analytics.py    ContentAnalytics, FeedbackLoopRecord
  views/            dashboard.py, pipeline.py, articles.py, search.py; __init__ re-exports
  services/
    trends/         discovery, intelligence, competitor, prediction
    research/       investigator, fact_verifier
    strategy.py, writer.py, social.py, memory.py
    seo.py          (from seo/services/seo_engine.py)
    visual.py       (from media_generation/services/visual_engine.py)
    approval.py     (from approval/services/workflow.py)
    publishing.py   (from publishing/services/publisher.py)
    analytics.py    (from analytics/services/analytics.py)
  pipeline/         orchestrator.py, newsroom.py, tasks.py
  tasks.py          one-line re-export of pipeline.tasks (Celery autodiscovery)
  utils/text.py     fit_to_column
  tests/            __init__.py, fakes.py (was llm_fakes.py), test_*.py
  management/, migrations/, templates/
```

Within a domain package, keep a module's name when it already says what it is.
`services/` sub-packages may be flat files when the domain is one module.

## Rules for every step

- **No behaviour changes.** Moves, renames and import rewrites only. Preserve
  every comment and docstring verbatim (CLAUDE.md).
- **No shims for deleted apps.** When code leaves an app, every importer
  anywhere in the repo is rewritten to the new path. `editorial.models` and
  `editorial.views` keep re-exports because they are packages now, not shims.
- **Celery task names are explicit strings** (`name='editorial.run_pipeline'`
  and similar); do not change them.
- **`git mv`** for every move so history follows the file.
- **Stage explicit paths only.** The working tree carries four unrelated
  deleted root `*.md` files (PERFORMANCE_*.md, SECURITY_SUMMARY.md) that must
  not be committed. Never `git add -A` or `git add .`.
- One commit per step, Conventional Commits, `refactor(editorial): ...`.

## How to run tests

From `brandtechsolution/`, with the venv interpreter and `--keepdb`:

```
cd brandtechsolution
.venv/bin/python manage.py test editorial research trends publishing approval analytics seo media_generation knowledge_base ai_workflows --keepdb --noinput
.venv/bin/python manage.py makemigrations --check --dry-run
```

Drop app labels from the test command once the app no longer exists.
`ai_workflows` is slow; give it a long timeout or run it in the background.
Never add a `TransactionTestCase` (it truncates the migration-created
EmbeddingSpace and breaks ~20 unrelated tests on the next `--keepdb` run).
The baseline failures are recorded by Phase 0; compare failing test *names*,
not just counts.

## Phase 0 — baseline

Run the test command above on the unchanged branch and record the
pass/fail/error counts and failing test names in this file under
"Baseline". Every later step must match it.

## Phase 1 — move code, no database change

Models move into `editorial/models/<domain>.py` but **keep their original app
label** with `class Meta: app_label = '<old app>'` (merge into any existing
Meta). Django keeps tracking them under the old app, so `makemigrations
--check` must report **no changes** after each step. The old app shrinks to
`__init__.py`, `apps.py` and `migrations/` and stays in `INSTALLED_APPS` until
Phase 2. Admin registrations move into `editorial/admin/`.

Steps, one commit each:

1. **editorial internals** — split `models.py`, `views.py`, `admin.py` into
   packages; move `orchestrator.py`, `newsroom.py`, `tasks.py` into
   `pipeline/`; `text.py` into `utils/`; tests into `tests/` with
   `llm_fakes.py` becoming `tests/fakes.py`. Rewrite importers
   (`research/test_verification_gate.py`, `ai_workflows/*`,
   `brandtechsolution/celery.py`, ...).
2. **seo**, 3. **media_generation**, 4. **analytics**, 5. **approval**,
   6. **publishing** — move services, models, admin and tests in.
7. **research** and **trends** — together, because `research` models
   foreign-key `trends.TrendTopic`.

Old-app tests move to `editorial/tests/test_<domain>.py`.

## Phase 2 — migration consolidation (single step, highest risk)

Problem: `editorial/0001_initial` depends on `trends/0001` and `research/0001`
and foreign-keys `research.verifiedfactreport` and `trends.trendtopic`;
`analytics`, `approval`, `media_generation` and `publishing` 0001 each depend
on `editorial/0001`. Deleting the old apps breaks that history.

Approach:

1. Remove every `app_label` override; models now belong to `editorial`.
2. Replace `editorial/migrations/0001` and `0002` with one migration,
   `0001_squashed_consolidation`, that creates **all 15 models** and declares
   `replaces = [('editorial', '0001_initial'), ('editorial', '0002_editorialpipelinerun')]`.
   Each moved model sets `db_table` to its current table name
   (`trends_trendtopic`, ...) so existing databases need no table change.
   Cross-model FKs point at `editorial.<model>`.
   - Existing databases: editorial 0001+0002 are recorded as applied, so the
     squash is treated as applied and nothing runs.
   - Fresh databases (including the test DB): the squash creates everything.
3. `0002_relabel_moved_content_types`: a `RunPython` that updates the
   existing `django_content_type` rows for the 11 moved models from their old
   app label to `editorial`, **before** Django would create new ones. This
   keeps `knowledge_base.MemoryDocument.content_type` (a generic FK) pointing
   at the same rows, and keeps admin log entries intact. If an `editorial`
   row already exists for a model (created by an earlier run), repoint
   `MemoryDocument` rows from the old row to it and delete the old row.
   No-op on fresh databases. Reverse: relabel back.
4. `0003_rename_moved_tables`: `AlterModelTable` each moved model to
   `editorial_<model>` (drop the `db_table` override). Renames are metadata
   only on PostgreSQL.
5. Delete the seven old app directories and remove them from
   `INSTALLED_APPS`. Rewrite any remaining string references.
6. Leftover `django_migrations` rows for the deleted apps are harmless; leave
   them (do not write code that deletes them).

Verification, all required:

- `makemigrations --check --dry-run` reports no changes.
- The full test command passes against the baseline (fresh test DB path:
  run once without `--keepdb` using `--noinput` so the test DB is rebuilt
  from the new migrations).
- **Existing-database path:** clone the dev database with
  `createdb -T <dev_db> editorial_consolidation_check` (PostgreSQL), point
  Django at the clone via an environment override, run `migrate`, and check
  that row counts for all 11 moved models and for `MemoryDocument` with a
  content type are unchanged and that those content types now say
  `editorial`. **Never run `migrate` against the real dev database.** Drop the
  clone afterwards.

## Phase 3 — docs

`CHANGELOG.md` (`### Changed` under `[Unreleased]`), `docs/ROADMAP.md`,
`README.md` architecture section, and `CLAUDE.md` / docs that list the apps.

## Deployment note

Production runs the same migrations: the squash is recognised as applied,
`0002` relabels content types, `0003` renames tables. No data is copied.

## Baseline

Recorded 2026-10-16 on `refactor/editorial-consolidation` before any change:

- Test command from "How to run tests": **669 tests, 0 failures, 0 errors** (OK).
- Failing test names: none.
- `makemigrations --check --dry-run`: "No changes detected".
