"""Persistent snapshots: upstream request counts, negative results and safe refreshes."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from github import GithubException

from brand.github_cache import (
    blocked_until, cache_scope, cached_document_audit, cached_repositories,
    record_failure, refresh_content, request_refresh, run_refresh, state_for,
)
from brand.github_service import GitHubService
from brand.models import GitHubRefreshState, GitHubRepositoryCache, Project
from brand.test_github import fake_repo, staff_with
from brand.test_repo_docs import GOOD_CHANGELOG, GOOD_ROADMAP
from brandtechsolution.config import config
from tasks.github import poll_repository
from tasks.models import Repository, Task


class CacheReadTests(TestCase):
    def setUp(self):
        token = patch.object(config, 'github_access_token', 'test-token')
        token.start(); self.addCleanup(token.stop)
        self.queue = patch('brand.github_cache.enqueue_refresh_job').start()
        self.addCleanup(patch.stopall)
        self.github = patch('brand.github_service.Github', side_effect=AssertionError('GET reached GitHub')).start()
        self.client.force_login(staff_with('manage_projects'))
        self.row = GitHubRepositoryCache.objects.create(
            scope=cache_scope(), github_repo_id=101, full_name='teklora/widget',
            metadata={'id': 101, 'name': 'widget', 'full_name': 'teklora/widget', 'html_url': 'https://github.com/teklora/widget', 'role': 'owner'},
            documents={'status': 'ok', 'problems': []}, readme_content='# Saved',
            recent_commits=[], content_checked_at=timezone.now(),
        )
        for key, value in [('catalogue', {}), ('account', {'login': 'teklora', 'organizations': []})]:
            state = state_for(key)
            state.refreshed_at, state.value = timezone.now(), value
            state.save()

    def test_warm_gets_use_database_even_after_memory_cache_reset(self):
        cache.clear()
        for _ in range(2):
            self.assertEqual(self.client.get('/api/github/repos/').json()['results'][0]['id'], 101)
            self.assertEqual(self.client.get('/api/github/account/').json()['login'], 'teklora')
            self.assertEqual(self.client.get('/api/github/repos/101/readme/').json()['readme'], '# Saved')
        self.github.assert_not_called()
        self.queue.assert_not_called()

    def test_project_edits_are_visible_without_github_refresh(self):
        project = Project.objects.create(title='Original', description='Original', github_repo_id=101)
        self.assertEqual(self.client.get('/api/github/repos/').json()['results'][0]['project']['title'], 'Original')
        Project.objects.filter(pk=project.pk).update(title='Edited locally')
        self.assertEqual(self.client.get('/api/github/repos/').json()['results'][0]['project']['title'], 'Edited locally')
        self.queue.assert_not_called()

    def test_absent_readme_and_empty_commits_are_known_cached_results(self):
        self.row.readme_content = None
        self.row.save()
        project = Project.objects.create(title='Empty', description='', github_repo_id=101, is_github_synced=True, cached_commits=[])
        for _ in range(2):
            self.assertEqual(self.client.get('/api/github/repos/101/readme/').status_code, 404)
            data = self.client.get(f'/api/projects/{project.pk}/commits/?refresh=1').json()
            self.assertEqual(data['commits'], [])
            self.assertFalse(data['pending'])
        self.queue.assert_not_called()
        self.github.assert_not_called()

    def test_cold_gets_queue_once_and_return_without_upstream_calls(self):
        GitHubRepositoryCache.objects.all().delete()
        GitHubRefreshState.objects.all().delete()
        for _ in range(2):
            self.assertEqual(self.client.get('/api/github/repos/').json()['results'], [])
            self.assertTrue(self.client.get('/api/github/account/').json()['pending'])
            self.assertEqual(self.client.get('/api/github/repos/999/readme/').status_code, 202)
        self.assertEqual(self.queue.call_count, 3)
        self.github.assert_not_called()

    def test_stale_list_returns_last_good_rows_while_refreshing(self):
        GitHubRefreshState.objects.filter(key='catalogue').update(refreshed_at=timezone.now()-timedelta(days=1))
        data = self.client.get('/api/github/repos/').json()
        self.assertEqual(len(data['results']), 1)
        self.assertTrue(data['cache']['stale'])
        self.assertTrue(data['cache']['refreshing'])
        self.queue.assert_called_once()

    def test_manual_refresh_is_post_capability_protected_and_coalesced(self):
        self.assertEqual(self.client.get('/api/github/refresh/').status_code, 405)
        for _ in range(2):
            self.assertEqual(self.client.post('/api/github/refresh/', {'kind': 'catalogue'}, content_type='application/json').status_code, 202)
        self.queue.assert_called_once()
        self.client.logout()
        self.assertEqual(self.client.post('/api/github/refresh/').status_code, 401)
        self.client.force_login(staff_with())
        self.assertEqual(self.client.post('/api/github/refresh/').status_code, 403)

    def test_invalid_refresh_requests_rejected_without_jobs(self):
        for data in [{'kind': 'other'}, {'kind': 'repository', 'repo_id': 'x'}, {'kind': 'repository', 'repo_id': -1}]:
            self.assertEqual(self.client.post('/api/github/refresh/', data, content_type='application/json').status_code, 400)
        self.queue.assert_not_called()

    def test_changing_credentials_does_not_expose_old_private_snapshots(self):
        with patch.object(config, 'github_access_token', 'different-token'):
            self.assertEqual(self.client.get('/api/github/repos/').json()['results'], [])
            self.assertTrue(self.client.get('/api/github/account/').json()['pending'])
        self.assertNotIn('test-token', self.row.scope)

    def test_expired_lease_can_be_recovered(self):
        state = state_for('catalogue')
        state.lease_until, state.running = timezone.now()-timedelta(minutes=1), True
        state.save()
        self.assertTrue(request_refresh('catalogue', force=True))
        self.queue.assert_called_once()

    def test_failed_refresh_preserves_rows_and_records_generic_backoff(self):
        request_refresh('catalogue', force=True)
        args = self.queue.call_args.args
        with patch('brand.github_service.GitHubService.get_user_repositories', side_effect=GithubException(503, {'message':'secret-token-must-not-leak'}, {})):
            result = run_refresh(*args)
        self.assertIn('saved data', result['error'])
        state = state_for('catalogue')
        self.assertNotIn('secret-token', state.last_error)
        self.assertIsNotNone(state.retry_after)
        self.assertEqual(GitHubRepositoryCache.objects.get().readme_content, '# Saved')
        self.assertFalse(request_refresh('catalogue', force=True))

    def test_rate_limit_blocks_other_refreshes_and_task_polling_until_reset(self):
        reset = timezone.now()+timedelta(hours=1)
        record_failure('catalogue', GithubException(429, {'message':'rate limited'}, {'X-RateLimit-Reset': str(int(reset.timestamp()))}))
        self.assertGreaterEqual(blocked_until().timestamp(), int(reset.timestamp()))
        self.assertFalse(request_refresh('account', force=True))
        repository = Repository.objects.create(full_name='teklora/widget')
        upstream = Mock()
        self.assertIn('skipped', poll_repository(repository, upstream))
        upstream.get_repo.assert_not_called()

    def test_old_credential_job_and_completed_duplicate_do_not_run(self):
        request_refresh('account', force=True)
        args = self.queue.call_args.args
        with patch.object(config, 'github_access_token', 'new-token'):
            self.assertIn('skipped', run_refresh(*args))
        state = state_for('account')
        state.lease_until = None
        state.save()
        self.assertIn('skipped', run_refresh(*args))
        self.github.assert_not_called()


class SnapshotRefreshTests(TestCase):
    def setUp(self):
        patch.object(config, 'github_access_token', 'test-token').start()
        patch.object(config, 'github_username', 'teklora').start()
        self.addCleanup(patch.stopall)
        self.repo = fake_repo(commits=0)
        self.service = GitHubService.__new__(GitHubService)
        self.service.username = 'teklora'
        self.service.client = Mock()
        self.service.client.get_repo.return_value = self.repo

    def test_broker_sender_cannot_execute_eager_network_work_in_get(self):
        from brand.github_cache import enqueue_refresh_job
        from brandtechsolution.celery import app
        with patch.object(app, 'send_task') as send, patch.object(app, 'connection_for_write'):
            enqueue_refresh_job(cache_scope(), 'catalogue', None, 'lease-token')
        self.assertEqual(send.call_args.args[0], 'brand.refresh_github_cache')
        self.assertFalse(send.call_args.kwargs['retry'])

    def test_unchanged_content_is_reused_across_service_instances(self):
        refresh_content(self.service, self.repo)
        cache.clear()
        another = GitHubService.__new__(GitHubService)
        refresh_content(another, self.repo)
        self.repo.get_readme.assert_called_once()
        self.repo.get_commits.assert_called_once()
        self.assertEqual(GitHubRepositoryCache.objects.get().recent_commits, [])

    def test_new_push_refreshes_content_and_does_not_fetch_commit_stats(self):
        refresh_content(self.service, self.repo)
        self.repo.pushed_at += timedelta(minutes=1)
        refresh_content(self.service, self.repo)
        self.assertEqual(self.repo.get_readme.call_count, 2)
        self.assertEqual(self.repo.get_commits.call_count, 2)
        commit = SimpleNamespace(sha='a'*40, commit=SimpleNamespace(message='A commit', author=None))
        self.repo.get_commits.return_value.__getitem__.side_effect = lambda page: [commit]
        self.assertEqual(self.service._fetch_commits_from_github(self.repo)[0]['message'], 'A commit')

    def test_failed_payload_refresh_keeps_previous_good_content(self):
        refresh_content(self.service, self.repo)
        self.repo.pushed_at += timedelta(minutes=1)
        self.repo.get_readme.return_value.decoded_content = b'# Changed'
        self.repo.get_commits.side_effect = GithubException(500, {'message':'offline'}, {})
        with self.assertRaises(GithubException):
            refresh_content(self.service, self.repo)
        self.assertEqual(GitHubRepositoryCache.objects.get().readme_content, '# Widget')

    def document_repo(self):
        files = {'CHANGELOG.md': GOOD_CHANGELOG, 'ROADMAP.md': GOOD_ROADMAP}
        entries = [SimpleNamespace(name=name, type='file', size=500, sha=name+'-sha') for name in ['README.md','LICENSE','CHANGELOG.md','ROADMAP.md']]
        def contents(path):
            return entries if path == '' else SimpleNamespace(decoded_content=files[path].encode())
        self.repo.get_contents.side_effect = contents
        return files, entries

    def test_document_bodies_persist_and_unchanged_hashes_avoid_downloads(self):
        self.document_repo()
        cached_document_audit(self.repo)
        cache.clear()
        cached_document_audit(self.repo)
        self.assertEqual(self.repo.get_contents.call_count, 3)
        self.repo.pushed_at += timedelta(minutes=1)
        cached_document_audit(self.repo)
        # New root listing; unchanged CHANGELOG/ROADMAP blobs are reused.
        self.assertEqual(self.repo.get_contents.call_count, 4)
        row = GitHubRepositoryCache.objects.get()
        self.assertEqual(row.document_contents['ROADMAP.md'], GOOD_ROADMAP)

    def test_in_memory_document_cache_is_scoped_to_credentials_too(self):
        self.document_repo()
        GitHubService.audit_repo_docs(self.repo)
        first_calls = self.repo.get_contents.call_count
        with patch.object(config, 'github_access_token', 'another-token'):
            GitHubService.audit_repo_docs(self.repo)
        self.assertGreater(self.repo.get_contents.call_count, first_calls)

    def test_only_changed_document_body_is_downloaded(self):
        files, entries = self.document_repo()
        cached_document_audit(self.repo)
        self.repo.pushed_at += timedelta(minutes=1)
        next(entry for entry in entries if entry.name == 'CHANGELOG.md').sha = 'new-sha'
        files['CHANGELOG.md'] += '\n'
        cached_document_audit(self.repo)
        self.assertEqual(self.repo.get_contents.call_count, 5)

    def test_cached_root_sha_reuses_unchanged_readme_after_code_push(self):
        self.document_repo()
        cached_document_audit(self.repo)
        self.repo.get_readme.return_value.sha = 'README.md-sha'
        refresh_content(self.service, self.repo)
        self.repo.pushed_at += timedelta(minutes=1)
        cached_document_audit(self.repo)
        refresh_content(self.service, self.repo)
        self.repo.get_readme.assert_called_once()
        self.assertEqual(self.repo.get_commits.call_count, 2)

    def test_task_polling_skips_unchanged_commit_and_document_payloads(self):
        self.document_repo()
        repository = Repository.objects.create(full_name='teklora/widget')
        poll_repository(repository, self.service.client)
        calls = (self.repo.get_commits.call_count, self.repo.get_contents.call_count)
        repository.refresh_from_db()
        result = poll_repository(repository, self.service.client)
        self.assertTrue(result['unchanged'])
        self.assertEqual((self.repo.get_commits.call_count, self.repo.get_contents.call_count), calls)
        self.assertEqual(self.repo.get_contents.call_count, 3)  # No second roadmap fetch.
        self.assertTrue(Task.objects.filter(source=Task.ROADMAP, title="a sub-step").exists())


class PushInvalidationTests(TestCase):
    setUp = CacheReadTests.setUp

    def test_only_default_branch_push_invalidates_and_queues_affected_snapshot(self):
        import hashlib
        import hmac
        import json
        from django.test import override_settings

        Repository.objects.create(full_name='teklora/widget')
        other = GitHubRepositoryCache.objects.create(scope=cache_scope(), github_repo_id=202,
                    full_name='teklora/other', content_checked_at=timezone.now())
        def push(ref):
            payload = {'repository': {'full_name': 'teklora/widget', 'default_branch': 'main'},
                       'ref': ref, 'commits': [{'id': 'a'*40, 'message': 'Update app', 'author': {}, 'modified': ['app.py']}]}
            body = json.dumps(payload).encode()
            signature = 'sha256='+hmac.new(b'secret', body, hashlib.sha256).hexdigest()
            return self.client.post('/api/work/github/webhook/', body, content_type='application/json',
                                    HTTP_X_GITHUB_EVENT='push', HTTP_X_HUB_SIGNATURE_256=signature)
        with override_settings(GITHUB_WEBHOOK_SECRET='secret'):
            self.assertEqual(push('refs/heads/feature').status_code, 200)
            self.row.refresh_from_db()
            self.assertIsNotNone(self.row.content_checked_at)
            self.queue.assert_not_called()
            self.assertEqual(push('refs/heads/main').status_code, 200)
        self.row.refresh_from_db(); other.refresh_from_db()
        self.assertIsNone(self.row.content_checked_at)
        self.assertIsNotNone(other.content_checked_at)
        self.assertEqual(self.queue.call_args.args[1:3], ('repository', 101))

    def test_invalidated_readme_refreshes_even_if_previous_job_was_recent(self):
        state = state_for('repository:101')
        state.refreshed_at = timezone.now()
        state.save()
        self.row.content_checked_at = None
        self.row.save()
        self.assertEqual(self.client.get('/api/github/repos/101/readme/').status_code, 202)
        self.queue.assert_called_once()

    def test_confirmed_unavailable_snapshot_is_not_served_or_repeatedly_queued(self):
        self.row.available = False
        self.row.save()
        self.assertEqual(self.client.get('/api/github/repos/101/readme/').status_code, 404)
        self.assertEqual(self.client.get('/api/github/repos/').json()['results'], [])
        self.queue.assert_not_called()
