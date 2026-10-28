from unittest.mock import Mock, patch

from django.test import TestCase
from github import GithubException

from brand.repo_docs import check_documents
from tasks.github import apply_documentation_audit, poll_repository, push_touches_documents
from tasks.models import Repository, Task, TaskAssignment
from tasks.tests.test_workflow import make_staff


def audit(*problems, status='problems'):
    return {'status': status, 'problems': [
        {'file': file, 'code': 'test', 'message': message, 'fix': 'Use the required format.'}
        for file, message in problems
    ]}


class DocumentationRepairTest(TestCase):
    def setUp(self):
        self.repo = Repository.objects.create(full_name='example/site')
        self.findings = check_documents({}, {})
        self.findings['status'] = 'problems'
        self.user = make_staff('developer')

    def test_missing_four_documents_create_four_unassigned_repair_tasks(self):
        result = apply_documentation_audit(self.repo, self.findings)
        self.assertEqual(len(result['created']), 4)
        self.assertEqual(set(Task.objects.values_list('title', flat=True)), {
            'Update README.md', 'Update CHANGELOG.md', 'Update ROADMAP.md', 'Update LICENSE',
        })
        self.assertFalse(TaskAssignment.objects.exists())
        self.assertTrue(all(task.source == Task.DOCUMENTATION for task in Task.objects.all()))
        self.assertIn('Add README.md', Task.objects.get(title='Update README.md').description)

    def test_repeated_checks_are_idempotent_and_findings_grouped_by_document(self):
        findings = audit(('README.md', 'Too short'), ('README.md', 'Wrong case'))
        apply_documentation_audit(self.repo, findings)
        result = apply_documentation_audit(self.repo, findings)
        self.assertEqual(result, {'created': [], 'updated': [], 'resolved': []})
        task = Task.objects.get()
        self.assertIn('Too short', task.description)
        self.assertIn('Wrong case', task.description)
        self.assertEqual(task.activity.count(), 1)

    def test_findings_update_without_resetting_assignees_or_duplicating_tasks(self):
        apply_documentation_audit(self.repo, audit(('README.md', 'Missing')))
        task = Task.objects.get()
        TaskAssignment.objects.create(task=task, user=self.user)
        result = apply_documentation_audit(self.repo, audit(('README.md', 'Too short')))
        self.assertEqual(result['updated'], [task.pk])
        task.refresh_from_db()
        self.assertIn('Too short', task.description)
        self.assertNotIn('- Missing', task.description)
        self.assertEqual(task.assignments.get().user, self.user)
        self.assertEqual(Task.objects.count(), 1)

    def test_unassigned_resolved_task_is_hidden_and_reused_on_recurrence(self):
        findings = audit(('LICENSE', 'Missing'))
        apply_documentation_audit(self.repo, findings)
        task = Task.objects.get()
        result = apply_documentation_audit(self.repo, audit(status='ok'))
        self.assertEqual(result['resolved'], [task.pk])
        task.refresh_from_db()
        self.assertTrue(task.documentation_resolved)
        self.assertEqual(task.status, Task.OPEN)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/api/work/tasks/?workspace=backlog').json()['count'], 0)
        apply_documentation_audit(self.repo, findings)
        task.refresh_from_db()
        self.assertFalse(task.documentation_resolved)
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(self.client.get('/api/work/tasks/?workspace=backlog').json()['count'], 1)

    def test_successful_check_submits_assigned_work_for_review_never_approves(self):
        apply_documentation_audit(self.repo, audit(('README.md', 'Missing')))
        task = Task.objects.get()
        TaskAssignment.objects.create(task=task, user=self.user)
        with patch('tasks.github.notify_review_ready') as notify, self.captureOnCommitCallbacks(execute=True):
            apply_documentation_audit(self.repo, audit(status='ok'))
            apply_documentation_audit(self.repo, audit(status='ok'))
        notify.assert_called_once()
        task.refresh_from_db()
        self.assertEqual(task.status, Task.IN_REVIEW)
        self.assertIsNotNone(task.assignments.get().completed_at)
        self.assertTrue(task.documentation_resolved)

    def test_approved_work_remains_done_and_new_issue_creates_new_task(self):
        findings = audit(('README.md', 'Missing'))
        apply_documentation_audit(self.repo, findings)
        old = Task.objects.get()
        old.status = Task.DONE
        old.save()
        apply_documentation_audit(self.repo, findings)
        apply_documentation_audit(self.repo, findings)
        self.assertEqual(Task.objects.count(), 2)
        old.refresh_from_db()
        self.assertEqual(old.status, Task.DONE)
        self.assertEqual(Task.objects.exclude(pk=old.pk).get().status, Task.OPEN)

    def test_unknown_check_neither_creates_nor_resolves_work(self):
        self.assertEqual(apply_documentation_audit(self.repo, audit(status='unknown'))['created'], [])
        apply_documentation_audit(self.repo, audit(('README.md', 'Missing')))
        apply_documentation_audit(self.repo, audit(status='unknown'))
        self.assertFalse(Task.objects.get().documentation_resolved)

    def test_repairs_are_assignable_and_counts_include_both_sources(self):
        manager = make_staff('manager', ['manage_tasks'])
        apply_documentation_audit(self.repo, audit(('README.md', 'Missing')))
        task = Task.objects.get()
        Task.objects.create(title='Roadmap item', source=Task.ROADMAP, repository=self.repo)
        self.client.force_login(manager)
        rows = self.client.get('/api/work/tasks/?workspace=backlog').json()
        self.assertEqual(rows['count'], 2)
        self.assertEqual(self.client.get('/api/work/summary/').json()['backlog'], 2)
        self.assertEqual(self.client.get('/api/work/backlog-projects/').json()[0]['awaiting'], 2)
        self.assertIn('Documentation repair:', next(row for row in rows['results'] if row['id'] == task.pk)['roadmap_context'])
        self.assertEqual(self.client.get('/api/work/tasks/?workspace=board').json()['count'], 0)
        response = self.client.post(f'/api/work/tasks/{task.pk}/assign/', {'assignee_ids': [self.user.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/work/tasks/?workspace=board').json()['count'], 1)

    def test_resolved_task_cannot_be_assigned_from_stale_backlog(self):
        manager = make_staff('manager', ['manage_tasks'])
        apply_documentation_audit(self.repo, audit(('README.md', 'Missing')))
        task = Task.objects.get()
        apply_documentation_audit(self.repo, audit(status='ok'))
        self.client.force_login(manager)
        response = self.client.post(f'/api/work/tasks/{task.pk}/assign/', {'assignee_ids': [self.user.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 409)

    @patch('brand.github_service.GitHubService.audit_repo_docs')
    def test_empty_repository_still_produces_missing_document_tasks(self, shared_audit):
        shared_audit.return_value = {**self.findings, 'empty_repo': True}
        client = Mock()
        gh = client.get_repo.return_value
        gh.default_branch = 'main'
        gh.get_commits.side_effect = GithubException(409, 'empty repository')
        gh.get_contents.side_effect = GithubException(404, 'missing')
        result = poll_repository(self.repo, client)
        self.assertEqual(len(result['documentation']['created']), 4)
        self.assertEqual(result['roadmap'], None)
        self.repo.refresh_from_db()
        self.assertIsNotNone(self.repo.last_checked_at)

    @patch('brand.github_service.GitHubService.audit_repo_docs')
    def test_unknown_poll_does_not_advance_cursor_or_claim_missing_files(self, shared_audit):
        shared_audit.return_value = audit(status='unknown')
        client = Mock()
        client.get_repo.return_value.default_branch = 'main'
        with self.assertRaises(RuntimeError):
            poll_repository(self.repo, client)
        self.assertFalse(Task.objects.exists())
        self.repo.refresh_from_db()
        self.assertIsNone(self.repo.last_checked_at)

    def test_doc_changes_trigger_rechecks_including_removed_and_case_variants(self):
        for name in ['README.md', 'CHANGELOG.md', 'ROADMAP.md', 'docs/ROADMAP.md', 'LICENSE', 'license.md', 'LICENCE']:
            self.assertTrue(push_touches_documents({'commits': [{'removed': [name]}]}))
        self.assertFalse(push_touches_documents({'commits': [{'modified': ['app/models.py']}]}))


class DocumentationWebhookTest(TestCase):
    @patch('tasks.tasks.poll_repository_task.delay')
    def test_readme_push_queues_audit_even_when_roadmap_import_is_off(self, delay):
        import hashlib
        import hmac
        import json
        from django.test import override_settings

        repo = Repository.objects.create(full_name='example/site', track_roadmap=False)
        payload = {'repository': {'full_name': repo.full_name, 'default_branch': 'main'},
                   'ref': 'refs/heads/main', 'commits': [{'id': 'a' * 40, 'message': 'docs: improve readme',
                   'author': {}, 'modified': ['README.md']}]}
        body = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'test-secret', body, hashlib.sha256).hexdigest()
        with override_settings(GITHUB_WEBHOOK_SECRET='test-secret'):
            response = self.client.post('/api/work/github/webhook/', body, content_type='application/json',
                                       HTTP_X_GITHUB_EVENT='push', HTTP_X_HUB_SIGNATURE_256=signature)
        self.assertEqual(response.status_code, 200)
        delay.assert_called_once_with(repo.pk)
        self.assertEqual(response.json()["documentation"], "queued")
        self.assertNotIn("roadmap", response.json())
