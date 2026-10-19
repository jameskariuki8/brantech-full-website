"""Tests for the repository document standard (repo_docs) and its GitHub audit."""
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from github.GithubException import GithubException

from brand import repo_docs
from brand.github_service import GitHubService

GOOD_CHANGELOG = """# Changelog

## [Unreleased]

### Added
- A thing.

## [1.0.0] - 2026-10-01

### Fixed
- Another thing.
"""

GOOD_ROADMAP = """# Roadmap

### Milestone 1: Foundations *(Completed)*
- [x] Done work

### Milestone 2: Next
- [ ] Build the thing
  - [ ] a sub-step
- [x] Already built
"""

README_TEXT_SIZE = 500


def codes(problems):
    return {p['code'] for p in problems}


class ChangelogTests(SimpleTestCase):
    def test_conforming_changelog_has_no_problems(self):
        self.assertEqual(repo_docs.validate_changelog(GOOD_CHANGELOG), [])

    def test_missing_unreleased_section(self):
        text = "# Changelog\n\n## [1.0.0] - 2026-10-01\n\n### Added\n- x\n"
        self.assertIn('changelog_no_unreleased', codes(repo_docs.validate_changelog(text)))

    def test_free_form_release_heading(self):
        text = GOOD_CHANGELOG + "\n## Version two\n\n### Added\n- y\n"
        self.assertIn('changelog_bad_release_heading', codes(repo_docs.validate_changelog(text)))

    def test_unknown_section_name(self):
        text = "# Changelog\n\n## [Unreleased]\n\n### Stuff\n- x\n"
        self.assertIn('changelog_bad_section', codes(repo_docs.validate_changelog(text)))

    def test_empty_section_is_reported(self):
        text = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n### Fixed\n- x\n"
        found = repo_docs.validate_changelog(text)
        self.assertIn('changelog_empty_section', codes(found))
        self.assertIn('Unreleased / Added', [p for p in found if p['code'] == 'changelog_empty_section'][0]['message'])


class RoadmapTests(SimpleTestCase):
    def test_conforming_roadmap_has_no_problems(self):
        self.assertEqual(repo_docs.validate_roadmap(GOOD_ROADMAP), [])

    def test_parse_reads_status_tasks_and_depth(self):
        ms = repo_docs.parse_roadmap(GOOD_ROADMAP)
        self.assertEqual([m['number'] for m in ms], [1, 2])
        self.assertTrue(ms[0]['done'])
        self.assertFalse(ms[1]['done'])
        self.assertEqual([t['depth'] for t in ms[1]['tasks']], [0, 1, 0])

    def test_emoji_headings_and_h2_milestones_parse(self):
        ms = repo_docs.parse_roadmap("# R\n\n## \U0001F680 Milestone 3: Ship it *(In Progress)*\n- [ ] a\n")
        self.assertEqual(ms[0]['number'], 3)
        self.assertEqual(ms[0]['title'], 'Ship it')

    def test_open_tasks_skip_finished_milestones_and_subtasks(self):
        ready = repo_docs.open_roadmap_tasks(repo_docs.parse_roadmap(GOOD_ROADMAP))
        self.assertEqual([t['title'] for t in ready], ['Build the thing'])
        self.assertEqual(ready[0]['milestone'], 2)

    def test_checkboxes_in_code_fences_are_ignored(self):
        text = "# R\n\n### Milestone 1: A\n```\n- [ ] not real\n```\n- [ ] real\n"
        self.assertEqual(len(repo_docs.parse_roadmap(text)[0]['tasks']), 1)

    def test_no_milestones(self):
        self.assertIn('roadmap_no_milestones', codes(repo_docs.validate_roadmap("# Roadmap\n\nSoon.\n")))

    def test_empty_milestone(self):
        text = "# R\n\n### Milestone 1: A\n\n### Milestone 2: B\n- [ ] x\n"
        self.assertIn('roadmap_empty_milestone', codes(repo_docs.validate_roadmap(text)))

    def test_duplicate_numbers(self):
        text = "# R\n\n### Milestone 1: A\n- [ ] x\n\n### Milestone 1: B\n- [ ] y\n"
        self.assertIn('roadmap_duplicate_milestones', codes(repo_docs.validate_roadmap(text)))

    def test_all_checked_but_milestone_not_finished(self):
        text = "# R\n\n### Milestone 1: A\n- [x] x\n"
        self.assertIn('roadmap_no_open_tasks', codes(repo_docs.validate_roadmap(text)))


class CheckDocumentsTests(SimpleTestCase):
    def good_root(self):
        return {'README.md': README_TEXT_SIZE, 'CHANGELOG.md': 100, 'ROADMAP.md': 100, 'LICENSE': 1000}

    def good_contents(self):
        return {'CHANGELOG.md': GOOD_CHANGELOG, 'ROADMAP.md': GOOD_ROADMAP}

    def test_complete_repo_is_ok(self):
        result = repo_docs.check_documents(self.good_root(), self.good_contents())
        self.assertTrue(result['ok'], result['problems'])
        self.assertEqual(result['roadmap']['open_tasks'], 1)

    def test_empty_repo_reports_all_four_missing(self):
        result = repo_docs.check_documents({}, {})
        self.assertEqual(codes(result['problems']),
                         {'readme_missing', 'license_missing', 'changelog_missing', 'roadmap_missing'})

    def test_misspelt_license_is_named_not_called_missing(self):
        root = self.good_root()
        del root['LICENSE']
        root['LISENCE.md'] = 900
        found = codes(repo_docs.check_documents(root, self.good_contents())['problems'])
        self.assertEqual(found, {'license_misspelt'})

    def test_license_md_is_accepted(self):
        root = self.good_root()
        root['LICENSE.md'] = root.pop('LICENSE')
        self.assertTrue(repo_docs.check_documents(root, self.good_contents())['ok'])

    def test_wrong_case_is_flagged(self):
        root = self.good_root()
        root['Changelog.md'] = root.pop('CHANGELOG.md')
        contents = {'Changelog.md': GOOD_CHANGELOG, 'ROADMAP.md': GOOD_ROADMAP}
        self.assertEqual(codes(repo_docs.check_documents(root, contents)['problems']), {'changelog_wrong_case'})

    def test_stub_readme(self):
        root = self.good_root()
        root['README.md'] = 12
        self.assertEqual(codes(repo_docs.check_documents(root, self.good_contents())['problems']), {'readme_too_short'})

    def test_roadmap_in_docs_directory_counts(self):
        root = self.good_root()
        del root['ROADMAP.md']
        result = repo_docs.check_documents(
            root, {'CHANGELOG.md': GOOD_CHANGELOG, 'docs/ROADMAP.md': GOOD_ROADMAP}, {'ROADMAP.md': 100})
        self.assertTrue(result['ok'], result['problems'])
        self.assertEqual(result['present']['ROADMAP.md'], 'docs/ROADMAP.md')

    def test_unreadable_file_is_a_finding(self):
        contents = self.good_contents()
        contents['ROADMAP.md'] = None
        self.assertEqual(codes(repo_docs.check_documents(self.good_root(), contents)['problems']), {'roadmap_unreadable'})


def _entry(name, kind='file', size=500):
    return SimpleNamespace(name=name, type=kind, size=size)


def _content(text):
    return SimpleNamespace(decoded_content=text.encode())


class AuditRepoDocsTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        with patch('brand.github_service.config') as cfg:
            cfg.github_access_token = 'ghp_x'
            cfg.github_username = 'me'
            self.service = GitHubService()

    def repo(self, files, texts=None, docs_dir=None):
        texts = texts or {}
        repo = MagicMock()
        repo.id = 7
        repo.full_name = 'me/thing'
        repo.pushed_at = datetime(2026, 10, 1, tzinfo=dt_timezone.utc)

        def get_contents(path):
            if path == '':
                return files
            if path == 'docs':
                return docs_dir
            return _content(texts[path])
        repo.get_contents.side_effect = get_contents
        return repo

    def test_conforming_repository(self):
        repo = self.repo(
            [_entry('README.md'), _entry('LICENSE'), _entry('CHANGELOG.md'), _entry('ROADMAP.md')],
            {'CHANGELOG.md': GOOD_CHANGELOG, 'ROADMAP.md': GOOD_ROADMAP})
        result = self.service.audit_repo_docs(repo)
        self.assertEqual(result['status'], 'ok')

    def test_result_is_cached_until_the_next_push(self):
        repo = self.repo([_entry('README.md')])
        self.service.audit_repo_docs(repo)
        calls = repo.get_contents.call_count
        self.service.audit_repo_docs(repo)
        self.assertEqual(repo.get_contents.call_count, calls)
        repo.pushed_at = datetime(2026, 10, 2, tzinfo=dt_timezone.utc)
        self.service.audit_repo_docs(repo)
        self.assertGreater(repo.get_contents.call_count, calls)

    def test_empty_repository(self):
        repo = MagicMock()
        repo.id = 8
        repo.pushed_at = None
        repo.get_contents.side_effect = GithubException(404, {'message': 'This repository is empty.'}, {})
        result = self.service.audit_repo_docs(repo)
        self.assertEqual(result['status'], 'problems')
        self.assertTrue(result['empty_repo'])
        self.assertEqual(len(result['problems']), 4)

    def test_github_failure_is_unknown_not_ok(self):
        repo = MagicMock()
        repo.id = 9
        repo.pushed_at = None
        repo.get_contents.side_effect = GithubException(500, {'message': 'boom'}, {})
        result = self.service.audit_repo_docs(repo)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('error', result)

    def test_roadmap_found_in_docs(self):
        repo = self.repo(
            [_entry('README.md'), _entry('LICENSE'), _entry('CHANGELOG.md'), _entry('docs', 'dir')],
            {'CHANGELOG.md': GOOD_CHANGELOG, 'docs/ROADMAP.md': GOOD_ROADMAP},
            docs_dir=[_entry('ROADMAP.md')])
        self.assertEqual(self.service.audit_repo_docs(repo)['status'], 'ok')


class AccountInfoTests(SimpleTestCase):
    def service(self, token, user_type, login='teklorasolutionsltd', configured='teklorasolutionsltd'):
        with patch('brand.github_service.config') as cfg:
            cfg.github_access_token = token
            cfg.github_username = configured
            svc = GitHubService()
        user = MagicMock()
        user.login = login
        user.type = user_type
        user.get_orgs.return_value = [SimpleNamespace(login='Teklora-solutions')]
        svc.client = MagicMock()
        svc.client.get_user.return_value = user
        svc.client.oauth_scopes = ['repo', 'read:org']
        return svc

    def test_personal_account(self):
        with patch('brand.github_service.config') as cfg:
            cfg.github_access_token = 'ghp_abc'
            info = self.service('ghp_abc', 'User').get_account_info()
        self.assertFalse(info['is_organization'])
        self.assertEqual(info['token_kind'], 'classic personal access token')
        self.assertEqual(info['organizations'], ['Teklora-solutions'])
        self.assertTrue(info['username_matches'])

    def test_organization_account(self):
        with patch('brand.github_service.config') as cfg:
            cfg.github_access_token = 'ghs_abc'
            info = self.service('ghs_abc', 'Organization').get_account_info()
        self.assertTrue(info['is_organization'])

    def test_configured_username_mismatch_is_reported(self):
        with patch('brand.github_service.config') as cfg:
            cfg.github_access_token = 'ghp_abc'
            info = self.service('ghp_abc', 'User', configured='someone-else').get_account_info()
        self.assertFalse(info['username_matches'])
