# Repository Document Standard

Status: implemented (checker and GitHub Manager alert). Task list from ROADMAP.md: planned.

Every repository tracked in the GitHub Manager must carry four files at its root. The
manager flags any repository that does not, and the Documents tab of that repository says
exactly which file is wrong and how to fix it. The checker is `brand/repo_docs.py`.

| File | Required | Checked for |
|------|----------|-------------|
| `README.md` | yes | present, exact name, at least 200 bytes |
| `LICENSE` (or `LICENSE.md`, `LICENSE.txt`) | yes | present, not empty. `LISENCE.md` and `LICENCE` are reported as misspelt |
| `CHANGELOG.md` | yes | present, follows the format below |
| `ROADMAP.md` | yes | present, follows the format below. `docs/ROADMAP.md` is accepted |

File names are matched exactly (upper case). `Changelog.md` is reported with the rename to make.

## CHANGELOG.md

[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) with Semantic Versioning.

```markdown
# Changelog

## [Unreleased]

### Added
- **Short name**: what changed and why it matters.

### Fixed
- ...

## [1.2.0] - 2026-10-20

### Changed
- ...
```

Rules the checker enforces:

1. One `# ` title.
2. A `## [Unreleased]` section. New work is logged there until a version is cut.
3. Releases are `## [MAJOR.MINOR.PATCH] - YYYY-MM-DD`, newest first.
4. Entries sit under `### ` headings from: Added, Changed, Deprecated, Removed, Fixed, Security.
5. Entries are `- ` list items. A heading with no entries is reported.

## ROADMAP.md

```markdown
# <Project> Roadmap

### Milestone 1: Short name *(Completed)*
- [x] A finished task

### Milestone 2: Short name *(In Progress)*
- [ ] A task someone can pick up
  - [ ] A sub-step (not listed as its own task)
- [x] A task already done
```

Rules the checker enforces:

1. One `# ` title.
2. Milestones are headings of level 2 or 3 containing `Milestone <number>`. Numbers are unique.
   Leading emoji and `**bold**` are ignored.
3. An optional italic status in parentheses closes the heading. `Completed`, `Done`, `Shipped`
   and `Released` mark the milestone finished. Anything else (`In Progress`, `Planned`) is open.
4. Every milestone lists its work as checkbox items (`- [ ]` open, `- [x]` done).
5. Checkbox lines inside code fences are ignored.
6. A roadmap whose tasks are all checked must mark its milestones finished, or add the next tasks.

### Ready-to-assign tasks

`brand.repo_docs.open_roadmap_tasks()` turns a roadmap into the list used for manual
assignment: every unchecked, top-level checkbox under a milestone that is not finished,
as `{milestone, milestone_title, title}`. Nested checkboxes are sub-steps of the item
above them and are not listed separately. Wiring this list into Teklora Admin Tasks is a
roadmap item, not part of this change.

## Whose token

`GET /api/github/account/` reports the account that owns `GITHUB_ACCESS_TOKEN`. A personal
access token always belongs to a user account even when it reaches an organisation's
repositories; only a fine-grained token with an organisation as resource owner, or a GitHub
App installation token, acts as the organisation. The manager shows the account type, the
token kind and the organisations the account belongs to, and warns when `GITHUB_USERNAME`
does not match the token's owner.

## Cost

Each repository costs one contents listing, plus one read each for CHANGELOG and ROADMAP.
Results are cached for 6 hours and keyed on the repository's last push, so a push re-checks
immediately and a Reload costs nothing.
