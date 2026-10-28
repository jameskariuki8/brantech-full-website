import hashlib
import hmac
import json
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from github import GithubException

from staff.models import StaffProfile
from tasks.github import (
    Commit, apply_commits, apply_roadmap, choose_assignee, fetch_roadmap,
    poll_all, poll_repository, referenced_tasks, roadmap_items,
)
from tasks.models import Repository, Task, TaskAssignment, TaskCommit
from tasks.tests.test_workflow import make_staff

ROADMAP = '''# Roadmap
### Milestone 1: Board *(In Progress)*
- [ ] Task automation
  - [ ] Build Django API
  - [ ] Build template page
### Milestone 2: Old *(Completed)*
- [ ] Old task
'''


class AutomationTest(TestCase):
    def setUp(self):
        self.repo = Repository.objects.create(full_name='example/site')
        self.alice = make_staff('alice')
        self.bob = make_staff('bob')
        for user, role in [(self.alice, 'Backend Developer'), (self.bob, 'Frontend Developer')]:
            StaffProfile.objects.update_or_create(user=user, defaults={
                'is_onboarded': True, 'coding_languages': ['Python'],
                'frameworks': ['Django'], 'primary_role': role,
                'github_username': 'https://github.com/' + user.username,
            })
        self.task = Task.objects.create(title='API work', repository=self.repo)
        TaskAssignment.objects.create(task=self.task, user=self.alice)

    def commit(self, message=None, sha='a' * 40):
        return Commit(sha, message or f'Closes Task #{self.task.pk}', 'alice',
                      f'https://github.com/example/site/commit/{sha}', timezone.now())

    def test_reference_and_merge_parsing(self):
        for message in ['Merge branch \'feat/task-42-board\'', 'Merge pull request #7 from owner/fix/task-42-board']:
            self.assertEqual(referenced_tasks(message), ({42}, {42}))
        self.assertEqual(referenced_tasks('feat: [TASK #42] refs Task #9'), ({42, 9}, set()))
        for word in ['Close', 'Closes', 'Closed', 'Fix', 'Fixes', 'Fixed', 'Resolve', 'Resolved', 'Completes', 'Done']:
            self.assertEqual(referenced_tasks(f'{word} Task #42'), ({42}, {42}))

    def test_feature_commit_promoted_and_duplicate_is_idempotent(self):
        commit = self.commit()
        apply_commits(self.repo, [commit], False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)
        with patch('tasks.github.notify_review_ready') as notify, self.captureOnCommitCallbacks(execute=True):
            apply_commits(self.repo, [commit], True)
            apply_commits(self.repo, [commit], True)
        self.assertEqual(notify.call_count, 1)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.IN_REVIEW)
        self.assertEqual(TaskCommit.objects.count(), 1)
        self.assertEqual(self.task.activity.filter(kind='commit').count(), 1)
        self.assertEqual(TaskCommit.objects.get().author, self.alice)
        self.assertTrue(TaskCommit.objects.get().on_default_branch)

    def test_duplicate_does_not_finish_reopened_work(self):
        apply_commits(self.repo, [self.commit()], True)
        self.task.assignments.update(completed_at=None)
        Task.objects.filter(pk=self.task.pk).update(status=Task.OPEN)
        apply_commits(self.repo, [self.commit()], True)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)

    def test_other_repository_cannot_finish_linked_task(self):
        other = Repository.objects.create(full_name='other/site')
        apply_commits(other, [self.commit()], True)
        self.assertFalse(TaskCommit.objects.exists())
        self.assertFalse(self.task.assignments.exclude(completed_at=None).exists())

    def test_reference_without_closing_only_links(self):
        apply_commits(self.repo, [self.commit(f'Work on Task #{self.task.pk}')], True)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)

    def test_approved_and_unassigned_are_not_submitted(self):
        self.task.status = Task.DONE
        self.task.save()
        apply_commits(self.repo, [self.commit()], True)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.DONE)
        self.task.assignments.all().delete()
        self.task.status = Task.OPEN
        self.task.save()
        apply_commits(self.repo, [self.commit(sha='b' * 40)], True)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)

    def test_unknown_task_ignored_and_unknown_author_preserved(self):
        apply_commits(self.repo, [self.commit('Task #999999')], True)
        self.assertFalse(TaskCommit.objects.exists())
        commit = self.commit()
        commit.author_login = 'external'
        apply_commits(self.repo, [commit], False)
        row = TaskCommit.objects.get()
        self.assertIsNone(row.author)
        self.assertIn('external', self.task.activity.get(kind='commit').body)

    def test_leaf_items_create_once_and_wait_for_assignment(self):
        self.assertEqual(len(roadmap_items(ROADMAP)), 3)
        result = apply_roadmap(self.repo, ROADMAP)
        self.assertEqual(len(result['created']), 2)
        self.assertEqual(apply_roadmap(self.repo, ROADMAP)['created'], [])
        backend = Task.objects.get(title='Build Django API')
        frontend = Task.objects.get(title='Build template page')
        self.assertFalse(backend.assignments.exists())
        self.assertFalse(frontend.assignments.exists())
        self.assertIn(f'Task #{backend.pk}', backend.description)

    def test_checked_item_finishes_and_removed_item_is_kept(self):
        apply_roadmap(self.repo, ROADMAP)
        TaskAssignment.objects.create(task=Task.objects.get(title='Build Django API'), user=self.alice)
        result = apply_roadmap(self.repo, ROADMAP.replace('[ ] Build Django', '[x] Build Django'))
        task = Task.objects.get(title='Build Django API')
        self.assertEqual(result['finished'], [task.pk])
        self.assertEqual(task.status, Task.IN_REVIEW)
        apply_roadmap(self.repo, '# Roadmap')
        self.assertTrue(Task.objects.filter(pk=task.pk).exists())

    def test_checked_roadmap_does_not_resubmit_after_rejection(self):
        apply_roadmap(self.repo, ROADMAP)
        TaskAssignment.objects.create(task=Task.objects.get(title='Build Django API'), user=self.alice)
        checked = ROADMAP.replace('[ ] Build Django', '[x] Build Django')
        apply_roadmap(self.repo, checked)
        task = Task.objects.get(title='Build Django API')
        task.assignments.update(completed_at=None)
        Task.objects.filter(pk=task.pk).update(status=Task.OPEN)
        self.assertEqual(apply_roadmap(self.repo, checked)['finished'], [])
        task.refresh_from_db()
        self.assertEqual(task.status, Task.OPEN)
        apply_roadmap(self.repo, ROADMAP)
        self.assertEqual(apply_roadmap(self.repo, checked)['finished'], [task.pk])

    def test_matching_manual_task_reused(self):
        manual = Task.objects.create(title='Build Django API')
        result = apply_roadmap(self.repo, ROADMAP)
        self.assertEqual(result['linked'], [manual.pk])
        self.assertEqual(Task.objects.filter(title=manual.title).count(), 1)

    def test_assignment_pause_and_no_skills_exclude_candidates(self):
        StaffProfile.objects.filter(user=self.alice).update(auto_assign=False)
        self.assertEqual(choose_assignee('Django API'), self.bob)
        StaffProfile.objects.filter(user=self.bob).update(coding_languages=[], frameworks=[])
        self.assertIsNone(choose_assignee('Django API'))

    def test_assignment_skills_then_load_then_username(self):
        StaffProfile.objects.update(primary_role='Fullstack', frameworks=[])
        StaffProfile.objects.filter(user=self.bob).update(coding_languages=['JavaScript'])
        self.assertEqual(choose_assignee('Python API'), self.alice)
        self.assertEqual(choose_assignee('Generic API'), self.bob)
        self.task.assignments.all().delete()
        self.assertEqual(choose_assignee('Generic API'), self.alice)

    def test_missing_roadmap_falls_back_but_access_errors_propagate(self):
        gh = Mock(default_branch='main')
        gh.get_contents.side_effect = [GithubException(404, 'missing'), Mock(decoded_content=ROADMAP.encode())]
        self.assertEqual(fetch_roadmap(gh), ROADMAP)
        gh.get_contents.side_effect = GithubException(403, 'forbidden')
        with self.assertRaises(GithubException):
            fetch_roadmap(gh)

    def test_poll_failure_does_not_advance_cursor(self):
        client = Mock()
        client.get_repo.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            poll_repository(self.repo, client)
        self.repo.refresh_from_db()
        self.assertIsNone(self.repo.last_checked_at)

    @patch("brand.github_service.GitHubService.audit_repo_docs", return_value={"status": "ok", "problems": []})
    def test_poll_updates_branch_and_cursor(self, audit):
        client = Mock()
        gh = client.get_repo.return_value
        gh.default_branch = 'develop'
        gh.get_commits.return_value = []
        gh.get_contents.return_value = Mock(decoded_content=ROADMAP.encode())
        poll_repository(self.repo, client)
        self.repo.refresh_from_db()
        self.assertEqual(self.repo.default_branch, 'develop')
        self.assertIsNotNone(self.repo.last_checked_at)

    def test_poll_all_continues_after_failure(self):
        Repository.objects.create(full_name='z/working')
        with patch('tasks.github._client'), patch('tasks.github.poll_repository', side_effect=[RuntimeError('offline'), {'ok': True}]):
            results = poll_all()
        self.assertEqual(results['z/working'], {'ok': True})
        self.repo.refresh_from_db()
        self.assertIn('saved data', self.repo.last_error)

    def test_link_command_is_repeatable(self):
        for _ in range(2):
            call_command('link_repo', 'https://github.com/example/site.git', stdout=StringIO())
        self.assertEqual(Repository.objects.count(), 1)


@override_settings(GITHUB_WEBHOOK_SECRET='test-secret')
class WebhookTest(TestCase):
    setUp = AutomationTest.setUp
    def send(self, payload, event='push', signed=True):
        body = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'test-secret', body, hashlib.sha256).hexdigest()
        return self.client.post('/api/work/github/webhook/', body, content_type='application/json',
                                HTTP_X_GITHUB_EVENT=event, HTTP_X_HUB_SIGNATURE_256=signature if signed else '')

    def payload(self):
        return {'repository': {'full_name': self.repo.full_name, 'default_branch': 'main'},
                'ref': 'refs/heads/main', 'commits': [{'id': 'a'*40,
                'message': f'Closes Task #{self.task.pk}', 'author': {'username': 'alice'},
                'timestamp': '2026-10-28T10:00:00Z', 'modified': ['docs/ROADMAP.md']}]}

    def test_signature_ping_unknown_repo_and_missing_secret(self):
        self.assertEqual(self.send({}, signed=False).status_code, 403)
        self.assertEqual(self.send({}, event='ping').status_code, 200)
        self.assertEqual(self.send({'repository': {'full_name': 'unknown/repo'}}).status_code, 200)
        with override_settings(GITHUB_WEBHOOK_SECRET=''):
            self.assertEqual(self.send({}).status_code, 503)

    def test_malformed_payload_rejected(self):
        for payload in [[], {'repository': []}, {'repository': {}, 'commits': [None]}]:
            self.assertEqual(self.send(payload).status_code, 400)

    @patch('tasks.tasks.poll_repository_task.delay')
    def test_signed_push_finishes_and_queues_roadmap(self, delay):
        response = self.send(self.payload())
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.IN_REVIEW)
        delay.assert_called_once_with(self.repo.pk)

    def test_feature_push_links_without_finishing(self):
        payload = self.payload()
        payload['ref'] = 'refs/heads/feature'
        self.assertEqual(self.send(payload).status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)


class RepositoryAPITest(TestCase):
    def test_management_is_capability_restricted(self):
        staff = make_staff('staff')
        self.client.force_login(staff)
        for method, url in [('get', '/api/work/repos/'), ('post', '/api/work/repos/')]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        admin = make_staff('admin', ['manage_tasks'])
        self.client.force_login(admin)
        response = self.client.post('/api/work/repos/', {'full_name': 'https://github.com/example/site.git'})
        self.assertEqual(response.status_code, 201)
        repo = Repository.objects.get()
        self.assertEqual(repo.added_by, admin)
        self.assertEqual(repo.full_name, 'example/site')
        self.assertEqual(self.client.post('/api/work/repos/', {'full_name': 'EXAMPLE/site'}).status_code, 400)
        self.client.force_login(staff)
        for method, url in [('patch', f'/api/work/repos/{repo.pk}/'), ('delete', f'/api/work/repos/{repo.pk}/'), ('post', f'/api/work/repos/{repo.pk}/check/')]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 403)

    def test_check_failure_records_error(self):
        self.client.force_login(make_staff('admin', ['manage_tasks']))
        repo = Repository.objects.create(full_name='example/site')
        with patch('tasks.github.poll_repository', side_effect=RuntimeError('offline')):
            response = self.client.post(f'/api/work/repos/{repo.pk}/check/')
        self.assertEqual(response.status_code, 502)
        repo.refresh_from_db()
        self.assertEqual(repo.last_error, 'offline')
