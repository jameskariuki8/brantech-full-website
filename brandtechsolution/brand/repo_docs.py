"""
Repository document standard: README.md, CHANGELOG.md, ROADMAP.md and LICENSE.

Every repository tracked in the GitHub Manager must carry these four files, and
CHANGELOG.md and ROADMAP.md must follow a fixed shape so people, agents and the
platform read the same file the same way. The shape is written down in
docs/specs/2026-10-20-repo-docs-standard-spec.md.

This module is pure: it takes file names and text and returns findings. It
never talks to GitHub, so it is cheap to test and reusable for the task list
the roadmap will feed.
"""
import re
from typing import Any, Dict, List, Optional

README = 'README.md'
CHANGELOG = 'CHANGELOG.md'
ROADMAP = 'ROADMAP.md'
LICENSE = 'LICENSE'

# A roadmap may also live in docs/, which is where this repository keeps its own.
ROADMAP_FALLBACK_DIR = 'docs'

# License files GitHub itself recognises, plus the spellings people use.
LICENSE_NAMES = ('LICENSE', 'LICENSE.md', 'LICENSE.txt')
# A name that looks like the license file but is spelt wrong. Flagged with the
# right name rather than reported as "missing", because the file is there.
MISREAD_LICENSE_NAMES = ('LISENCE', 'LICENCE', 'LISCENSE')

README_MIN_CHARS = 200

CHANGELOG_SECTIONS = ('Added', 'Changed', 'Deprecated', 'Removed', 'Fixed', 'Security')

_HEADING = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
_MILESTONE = re.compile(r'milestone\s*(\d+)\s*[:.\-–—]?\s*(.*)', re.IGNORECASE)
_TASK = re.compile(r'^(\s*)[-*+]\s+\[([ xX])\]\s+(.*\S)\s*$')
_STATUS = re.compile(r'[*_]\((.+?)\)[*_]')
_VERSION = re.compile(r'^\[(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?)\]\s*-\s*(\d{4}-\d{2}-\d{2})\s*(?:\[YANKED\])?\s*$')
_BULLET = re.compile(r'^\s*[-*+]\s+\S')

DONE_STATUSES = ('completed', 'done', 'shipped', 'released')


def _problem(file: str, code: str, message: str, fix: str) -> Dict[str, str]:
    return {'file': file, 'code': code, 'message': message, 'fix': fix}


def _strip_markup(text: str) -> str:
    """Remove emphasis, code ticks and emoji-ish symbols from a heading or task."""
    text = re.sub(r'[*_`]', '', text)
    # Drop pictographs and variation selectors; keep ordinary punctuation.
    text = re.sub(r'[\U0001F000-\U0001FAFF☀-➿️]', '', text)
    return text.strip()


def _lines(text: str) -> List[str]:
    return (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')


# ─────────────────────────────────────────────────────────────────────────────
# ROADMAP.md
# ─────────────────────────────────────────────────────────────────────────────

def parse_roadmap(text: str) -> List[Dict[str, Any]]:
    """
    Read a roadmap into milestones.

    A milestone is a heading (level 2 or 3) that contains "Milestone <n>" and an
    optional italic status such as *(Completed)*. A task is a checkbox list item
    under a milestone. Nested checkboxes are sub-tasks of the item above them.

    Returns [{number, title, status, done, tasks: [{title, done, depth}]}].
    """
    milestones: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    in_fence = False

    for line in _lines(text):
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading = _HEADING.match(line)
        if heading:
            level, raw = len(heading.group(1)), heading.group(2)
            clean = _strip_markup(raw)
            found = _MILESTONE.search(clean)
            if level in (2, 3) and found:
                status_match = _STATUS.search(raw)
                status = status_match.group(1).strip() if status_match else ''
                title = _STATUS.sub('', raw)
                title = _strip_markup(title)
                title = _MILESTONE.sub(lambda m: m.group(2), title, count=1).strip(' :-')
                current = {
                    'number': int(found.group(1)),
                    'title': title or f'Milestone {found.group(1)}',
                    'status': status,
                    'done': status.lower().split('/')[0].strip() in DONE_STATUSES,
                    'tasks': [],
                }
                milestones.append(current)
            elif level <= 2 and current is not None:
                # A new top-level section that is not a milestone ends the last one.
                current = None
            continue

        task = _TASK.match(line)
        if task and current is not None:
            indent = len(task.group(1).replace('\t', '    '))
            current['tasks'].append({
                'title': _strip_markup(task.group(3)),
                'done': task.group(2).lower() == 'x',
                'depth': indent // 2,
            })

    return milestones


def open_roadmap_tasks(milestones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Unchecked, top-level tasks of milestones that are not finished: the assignable list."""
    ready = []
    for m in milestones:
        if m['done']:
            continue
        for t in m['tasks']:
            if not t['done'] and t['depth'] == 0:
                ready.append({'milestone': m['number'], 'milestone_title': m['title'], 'title': t['title']})
    return ready


def validate_roadmap(text: str) -> List[Dict[str, str]]:
    problems = []
    lines = _lines(text)
    if not any(re.match(r'^#\s+\S', l) for l in lines):
        problems.append(_problem(
            ROADMAP, 'roadmap_no_title', 'No title heading.',
            'Start the file with a single "# <Project> Roadmap" heading.'))

    milestones = parse_roadmap(text)
    if not milestones:
        problems.append(_problem(
            ROADMAP, 'roadmap_no_milestones', 'No milestones found.',
            'Add milestone headings such as "### Milestone 1: Name *(In Progress)*". '
            'Each one needs the word Milestone and a number.'))
        return problems

    numbers = [m['number'] for m in milestones]
    if len(set(numbers)) != len(numbers):
        problems.append(_problem(
            ROADMAP, 'roadmap_duplicate_milestones', 'Two milestones share a number.',
            'Number every milestone once: Milestone 1, Milestone 2, and so on.'))

    for m in milestones:
        if not m['tasks']:
            problems.append(_problem(
                ROADMAP, 'roadmap_empty_milestone',
                f'Milestone {m["number"]} ("{m["title"]}") has no tasks.',
                'List its work as checkbox items: "- [ ] Task" or "- [x] Done task".'))

    if not open_roadmap_tasks(milestones) and not all(m['done'] for m in milestones):
        problems.append(_problem(
            ROADMAP, 'roadmap_no_open_tasks',
            'Every task is checked, but a milestone is not marked finished.',
            'Add *(Completed)* to a finished milestone heading, or add the next tasks as "- [ ] ..." items.'))
    return problems


# ─────────────────────────────────────────────────────────────────────────────
# CHANGELOG.md
# ─────────────────────────────────────────────────────────────────────────────

def validate_changelog(text: str) -> List[Dict[str, str]]:
    problems = []
    lines = _lines(text)
    if not any(re.match(r'^#\s+\S', l) for l in lines):
        problems.append(_problem(
            CHANGELOG, 'changelog_no_title', 'No title heading.',
            'Start the file with "# Changelog".'))

    releases: List[str] = []
    bad_releases: List[str] = []
    sections_outside: List[str] = []
    bad_sections: List[str] = []
    empty_sections: List[str] = []
    current_release: Optional[str] = None
    current_section: Optional[str] = None
    section_bullets = 0
    in_fence = False

    def close_section():
        if current_section is not None and section_bullets == 0:
            empty_sections.append(f'{current_release} / {current_section}')

    for line in lines:
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _HEADING.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            if level == 2:
                close_section()
                current_section, section_bullets = None, 0
                if title.lower() == '[unreleased]':
                    current_release = 'Unreleased'
                    releases.append('Unreleased')
                elif _VERSION.match(title):
                    current_release = title.split(']')[0].lstrip('[')
                    releases.append(current_release)
                else:
                    current_release = None
                    bad_releases.append(title)
            elif level == 3:
                close_section()
                section_bullets = 0
                if current_release is None:
                    sections_outside.append(title)
                    current_section = None
                elif title in CHANGELOG_SECTIONS:
                    current_section = title
                else:
                    current_section = None
                    bad_sections.append(f'{current_release} / {title}')
            continue
        if current_section is not None and _BULLET.match(line):
            section_bullets += 1
    close_section()

    if 'Unreleased' not in releases:
        problems.append(_problem(
            CHANGELOG, 'changelog_no_unreleased', 'There is no "## [Unreleased]" section.',
            'Add "## [Unreleased]" above the newest release. New work is logged there until a version is cut.'))
    if bad_releases:
        problems.append(_problem(
            CHANGELOG, 'changelog_bad_release_heading',
            'Release heading(s) not in the expected form: ' + '; '.join(f'"{h}"' for h in bad_releases[:5]),
            'Write releases as "## [1.2.0] - 2026-10-20" (semantic version, ISO date), newest first.'))
    if bad_sections:
        problems.append(_problem(
            CHANGELOG, 'changelog_bad_section',
            'Unknown section(s): ' + '; '.join(bad_sections[:5]),
            'Group entries under "### " headings from: ' + ', '.join(CHANGELOG_SECTIONS) + '.'))
    if sections_outside:
        problems.append(_problem(
            CHANGELOG, 'changelog_section_outside_release',
            'Section(s) sit outside any release: ' + '; '.join(sections_outside[:5]),
            'Put every "### Added/Changed/Fixed" heading under "## [Unreleased]" or a version heading.'))
    if empty_sections:
        problems.append(_problem(
            CHANGELOG, 'changelog_empty_section',
            'Section(s) with no entries: ' + '; '.join(empty_sections[:5]),
            'Remove the empty heading, or add entries as "- " list items.'))
    if not releases:
        return problems
    if not any(
        _BULLET.match(l) for l in lines
    ):
        problems.append(_problem(
            CHANGELOG, 'changelog_no_entries', 'No entries found.',
            'Log each change as a "- " list item under its section.'))
    return problems


# ─────────────────────────────────────────────────────────────────────────────
# Whole-repository check
# ─────────────────────────────────────────────────────────────────────────────

def check_documents(
    root_files: Dict[str, int],
    contents: Dict[str, Optional[str]],
    docs_files: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Check a repository's documents.

    root_files: {file name: size in bytes} for the repository root.
    contents:   {file name: text} for CHANGELOG.md and ROADMAP.md when present.
                None means the file exists but could not be read.
    docs_files: {file name: size} for docs/, used only to find a ROADMAP.md.

    Returns {ok, problems, present, roadmap}. `present` maps each required
    document to the path it was found at, or None.
    """
    problems: List[Dict[str, str]] = []
    present: Dict[str, Optional[str]] = {}
    lower_root = {n.lower(): n for n in root_files}

    # README
    readme_name = lower_root.get('readme.md')
    present[README] = readme_name
    if not readme_name:
        problems.append(_problem(
            README, 'readme_missing', 'README.md is missing.',
            'Add README.md at the repository root: what the project is, how to run it, how to contribute.'))
    else:
        if readme_name != README:
            problems.append(_problem(
                README, 'readme_wrong_case', f'Found "{readme_name}", expected "README.md".',
                f'Rename {readme_name} to README.md.'))
        if root_files[readme_name] < README_MIN_CHARS:
            problems.append(_problem(
                README, 'readme_too_short', f'README.md is only {root_files[readme_name]} bytes.',
                f'Describe the project, how to run it and how to contribute (at least {README_MIN_CHARS} characters).'))

    # LICENSE
    license_name = next((n for n in LICENSE_NAMES if n in root_files), None)
    present[LICENSE] = license_name
    if not license_name:
        misspelt = next(
            (orig for low, orig in lower_root.items()
             if low.split('.')[0].upper() in MISREAD_LICENSE_NAMES),
            None)
        if misspelt:
            problems.append(_problem(
                LICENSE, 'license_misspelt', f'Found "{misspelt}", which is not a recognised license file name.',
                f'Rename {misspelt} to LICENSE (or LICENSE.md). GitHub only detects the license under that name.'))
        else:
            problems.append(_problem(
                LICENSE, 'license_missing', 'LICENSE is missing.',
                'Add a LICENSE file at the repository root containing the full license text.'))
    elif root_files[license_name] == 0:
        problems.append(_problem(LICENSE, 'license_empty', f'{license_name} is empty.',
                                 'Paste the full license text into it.'))

    # CHANGELOG
    changelog_name = lower_root.get('changelog.md')
    present[CHANGELOG] = changelog_name
    if not changelog_name:
        problems.append(_problem(
            CHANGELOG, 'changelog_missing', 'CHANGELOG.md is missing.',
            'Add CHANGELOG.md at the repository root following Keep a Changelog, starting with "## [Unreleased]".'))
    else:
        if changelog_name != CHANGELOG:
            problems.append(_problem(
                CHANGELOG, 'changelog_wrong_case', f'Found "{changelog_name}", expected "CHANGELOG.md".',
                f'Rename {changelog_name} to CHANGELOG.md.'))
        text = contents.get(changelog_name)
        if text is None:
            problems.append(_problem(CHANGELOG, 'changelog_unreadable', 'CHANGELOG.md could not be read.',
                                     'Check the file is plain text under 1 MB.'))
        else:
            problems.extend(validate_changelog(text))

    # ROADMAP
    roadmap_path = lower_root.get('roadmap.md')
    roadmap_text_key = roadmap_path
    if not roadmap_path and docs_files:
        in_docs = next((n for n in docs_files if n.lower() == 'roadmap.md'), None)
        if in_docs:
            roadmap_path = f'{ROADMAP_FALLBACK_DIR}/{in_docs}'
            roadmap_text_key = roadmap_path
    present[ROADMAP] = roadmap_path
    roadmap_summary = None
    if not roadmap_path:
        problems.append(_problem(
            ROADMAP, 'roadmap_missing', 'ROADMAP.md is missing.',
            'Add ROADMAP.md at the repository root: a title, then "### Milestone N: Name" headings with "- [ ] task" items.'))
    else:
        if roadmap_path.split('/')[-1] != ROADMAP:
            problems.append(_problem(
                ROADMAP, 'roadmap_wrong_case', f'Found "{roadmap_path}", expected "ROADMAP.md".',
                f'Rename it to ROADMAP.md.'))
        text = contents.get(roadmap_text_key)
        if text is None:
            problems.append(_problem(ROADMAP, 'roadmap_unreadable', 'ROADMAP.md could not be read.',
                                     'Check the file is plain text under 1 MB.'))
        else:
            problems.extend(validate_roadmap(text))
            milestones = parse_roadmap(text)
            roadmap_summary = {
                'milestones': len(milestones),
                'open_tasks': len(open_roadmap_tasks(milestones)),
                'done_tasks': sum(1 for m in milestones for t in m['tasks'] if t['done']),
            }

    return {
        'ok': not problems,
        'problems': problems,
        'present': present,
        'roadmap': roadmap_summary,
    }
