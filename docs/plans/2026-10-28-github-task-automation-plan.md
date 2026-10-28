# GitHub task automation

> The original repository-linking and automatic-assignment UX below is superseded by [the roadmap backlog specification](../specs/2026-10-28-roadmap-backlog-spec.md). Current behavior imports existing synced projects into an unassigned backlog; managers assign the work.

Date: 2026-10-28
Branch: `feat/github-task-automation`

## Problem

Tasks are handed out and ticked off by hand. The code already says which task it is for (`feat(staff): [Task #42] ...`, branches named `feat/task-42-slug`), and each repository's ROADMAP.md already says what is next, but the Tasks board knows neither:

- Nobody can see which commits went into a task, and a merged task still waits for its assignee to tick it.
- Open roadmap items are only counted (`brand/repo_docs.py: open_roadmap_tasks`), never turned into tasks.
- Some people should not be handed new work automatically (someone busy on another project).

## Design

### Linked repositories

`tasks.Repository` lists the repositories whose commits and roadmap drive the board: `full_name` (`owner/name`, unique), `default_branch`, `track_roadmap`, `last_checked_at`, `added_by`. It is separate from `brand.Project` because every Project row is shown on the public projects page, and the company's own website repository should not be.

Managed by `manage_tasks` holders through `/api/work/repos/` and the `link_repo` management command.

### Commits

A commit message refers to a task with `Task #N` (any case, brackets optional). A commit:

- **refers** to every task it names. The commit is stored once per task (`tasks.TaskCommit`: sha, message, author login, URL, time, whether it reached the default branch) and a `commit` entry is written to the task's timeline.
- **finishes** a task when it reaches the default branch and either says so (`Closes Task #N`, also closes/fixes/resolves/completes/done) or is the merge of a branch named `<type>/task-N-<slug>` (`Merge branch 'feat/task-42-...'` or a GitHub pull-request merge).

Finishing marks every outstanding assignment done, so the task moves to In review through the existing rule (`Task.refresh_review_state`) and the `manage_tasks` holders are emailed. It never approves a task: approval stays a person's decision. An approved task is left alone, and a task with no assignees is only linked.

The actor on the timeline is the staff member whose `StaffProfile.github_username` matches the commit author's GitHub login; otherwise the entry names the login.

Processing is idempotent by (task, sha), so a webhook delivery and a poll that both see a commit write it once.

### Roadmap

For each linked repository with `track_roadmap`, ROADMAP.md (root, then `docs/`) is parsed with the existing parser. The unit of work is a **leaf** item: a checkbox with no checkbox nested under it. Group headings such as "GitHub Admin Panel Integration" are not tasks.

- An unchecked leaf in an unfinished milestone with no task yet creates one (`source="roadmap"`, `roadmap_key="<milestone>:<normalised title>"`), with the milestone and parent item in the description, and assigns it (below). An unlinked manual task in no repository with the same title is linked instead of creating a duplicate.
- A checked leaf whose task is not finished finishes it, as a closing commit would.
- A removed item is left alone.

### Automatic assignment

Each roadmap task gets one assignee, chosen from active, onboarded staff who list coding languages or frameworks in their profile and have `StaffProfile.auto_assign` on (new, default on):

1. Area match: the task text is checked for frontend words (page, UI, template, modal, CSS, filter, dashboard...) and backend words (model, schema, API, sync, webhook, migration, database...). A Frontend role matches the first, a Backend role the second, Fullstack both.
2. Then a mention of one of their languages or frameworks.
3. Then the fewest unfinished assignments.
4. Then username, so the choice is repeatable.

`auto_assign` is shown and edited in the person editor (Staff & Groups) and is how someone working elsewhere is kept off new work. Manual assignment is unaffected.

### How changes reach the site

1. **Polling** (always on): a Celery Beat task, every `BEAT_TASK_REPO_INTERVAL` seconds (default 600), reads each linked repository's default-branch commits since the last check and its roadmap, with `GITHUB_ACCESS_TOKEN`. No GitHub setup is needed.
2. **Webhook** (optional, instant): `POST /api/work/github/webhook/` takes GitHub `push` events signed with `GITHUB_WEBHOOK_SECRET` (`X-Hub-Signature-256`). Without the secret it answers 503. A push that changes ROADMAP.md on the default branch queues a roadmap sync.

## Out of scope

- Pull request status on the board. Merges are covered; open pull requests are not shown.
- Assigning non-engineering work. Roadmaps describe code; other work is assigned by hand.

## Tests

`tasks/tests/test_github.py`: reference parsing; linking is idempotent; closing words and task branch merges finish a task only on the default branch; approved and unassigned tasks; author mapping; webhook signature, ping, unknown repository, missing secret; roadmap leaf extraction, task creation, title linking, checked items finishing tasks; assignment by area, skills, load and the `auto_assign` switch; the repository API is `manage_tasks` only.


## Completion checklist

- [x] Repository, commit and task-source models and migrations.
- [x] Commit parsing, default-branch promotion, idempotence and repository boundaries.
- [x] Roadmap leaf import, title reuse, developer ranking and serialized imports.
- [x] Persist checkbox transitions so rejected work is not resubmitted every poll.
- [x] Polling, signed webhook, repository APIs and `link_repo` command.
- [x] Repository management and commit details in Admin Tasks.
- [x] Manager-controlled automatic assignment switch in the person editor.
- [x] README, changelog, roadmap and feature specification.
- [x] Complete tasks/staff automated suites and migration consistency checks.


## Validation

- `python manage.py test tasks staff --noinput`: baseline suite passed (261 tests).
- Final tasks/staff suite passed with all additions: 288 tests, SQLite test database, in-process MD5 password hasher override for test speed only. Application settings are unchanged.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `node --check` passed for both modified admin JavaScript files.
- Node runtime assertions passed for commit detail rendering, HTML escaping and GitHub link scheme/host validation.
- `git diff --check` passed. Live GitHub delivery and production deployment were not exercised.
