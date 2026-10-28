from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from brand.models import Project
from tasks.github import apply_roadmap, discover_project_repositories, queue_project_import
from tasks.models import Repository, Task, TaskAssignment
from tasks.tests.test_github import ROADMAP
from tasks.tests.test_workflow import make_staff


class ProjectDiscoveryTest(TestCase):
    def project(self, **kwargs):
        return Project.objects.create(title='Website', description='Project description',
                                      github_url='https://github.com/example/site', **kwargs)

    def test_synced_project_reused_and_imports_are_unassigned(self):
        project = self.project(is_github_synced=True, github_repo_id=42)
        project_count = Project.objects.count()
        repo = discover_project_repositories()[0]
        self.assertEqual(repo.project, project)
        self.assertEqual(discover_project_repositories()[0].pk, repo.pk)
        self.assertEqual(Repository.objects.count(), 1)
        apply_roadmap(repo, ROADMAP)
        self.assertEqual(Task.objects.count(), 2)
        self.assertFalse(TaskAssignment.objects.exists())
        self.assertEqual(Project.objects.count(), project_count)

    def test_manual_project_not_discovered_and_invalid_urls_skipped(self):
        self.project()
        project = self.project(is_github_synced=True, github_repo_id=43)
        project.github_url = 'https://attacker.test/example/site'
        project.save()
        self.assertEqual(discover_project_repositories(), [])

    def test_existing_repository_keeps_import_setting(self):
        project = self.project(is_github_synced=True, github_repo_id=42)
        repo = Repository.objects.create(full_name='Example/Site', track_roadmap=False)
        self.assertEqual(discover_project_repositories()[0].pk, repo.pk)
        repo.refresh_from_db()
        self.assertEqual(repo.project_id, project.pk)
        self.assertFalse(repo.track_roadmap)

    @patch('tasks.tasks.poll_repository_task.delay')
    def test_project_sync_enqueues_after_commit(self, delay):
        project = self.project(is_github_synced=True, github_repo_id=42)
        with self.captureOnCommitCallbacks(execute=True):
            queue_project_import(project)
            delay.assert_not_called()
        delay.assert_called_once_with(Repository.objects.get().pk)

    def test_successful_github_sync_connects_project_import(self):
        from brand.github_service import GitHubService
        service = GitHubService.__new__(GitHubService)
        service.username = 'example'
        service.client = Mock()
        repo = service.client.get_repo.return_value
        repo.id = 42
        repo.name = 'site'
        repo.description = 'Description'
        repo.html_url = 'https://github.com/example/site'
        repo.owner.login = 'example'
        repo.get_commits.return_value.totalCount = 2
        repo.get_readme.return_value.decoded_content = b'# Site'
        with patch.object(service, '_fetch_commits_from_github', return_value=[]), patch('tasks.github.queue_project_import') as queue:
            result = service.sync_repositories([42])
        self.assertEqual(result['synced_count'], 1)
        queue.assert_called_once_with(Project.objects.get(github_repo_id=42))


class BacklogAPITest(TestCase):
    def setUp(self):
        self.manager = make_staff('manager', ['manage_tasks'])
        self.staff = make_staff('developer')
        self.other = make_staff('other')
        self.project = Project.objects.create(title='Customer Portal', description='Portal')
        self.repo = Repository.objects.create(full_name='example/portal', project=self.project)
        apply_roadmap(self.repo, ROADMAP)
        self.task = Task.objects.get(title='Build Django API')
        self.client.force_login(self.manager)

    def rows(self, query):
        return self.client.get('/api/work/tasks/?' + query).json()['results']

    def test_backlog_separate_from_board_and_includes_project_context(self):
        self.assertEqual(len(self.rows('workspace=backlog')), 2)
        self.assertEqual(self.rows('workspace=board'), [])
        row = self.rows('workspace=backlog')[0]
        self.assertEqual(row['project_title'], self.project.title)
        self.assertEqual(row['project_id'], self.project.pk)
        self.assertIn('Milestone 1', row['roadmap_context'])
        self.assertEqual(self.client.get('/api/work/summary/').json()['backlog'], 2)
        manual = Task.objects.create(title='Manual task')
        self.assertEqual(self.rows('workspace=board')[0]['id'], manual.pk)

    def test_matching_manual_task_joins_backlog_without_losing_assignments(self):
        self.repo.tasks.all().delete()
        manual = Task.objects.create(title='Build Django API')
        assigned = Task.objects.create(title='Build template page')
        TaskAssignment.objects.create(task=assigned, user=self.staff)
        apply_roadmap(self.repo, ROADMAP)
        self.assertEqual([row['id'] for row in self.rows('workspace=backlog')], [manual.pk])
        self.assertEqual(assigned.assignments.get().user, self.staff)
        self.assertEqual(self.rows('workspace=board')[0]['id'], assigned.pk)

    def test_search_project_filter_and_pagination(self):
        self.assertEqual(len(self.rows('workspace=backlog&q=Django')), 1)
        self.assertEqual(len(self.rows(f'workspace=backlog&repository={self.repo.pk}')), 2)
        self.assertEqual(self.rows('workspace=backlog&repository=999999'), [])
        response = self.client.get('/api/work/tasks/?workspace=backlog&page_size=1').json()
        self.assertEqual(response['count'], 2)
        self.assertIsNotNone(response['next'])
        self.assertEqual(self.client.get('/api/work/tasks/?workspace=backlog&repository=nope').status_code, 400)

    def test_assign_moves_item_to_board_and_records_activity(self):
        response = self.client.post(f'/api/work/tasks/{self.task.pk}/assign/', {'assignee_ids': [self.staff.pk, self.other.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.rows('workspace=backlog')), 1)
        self.assertEqual(self.rows('workspace=board')[0]['id'], self.task.pk)
        self.assertEqual(self.task.assignments.count(), 2)
        self.assertEqual(self.task.activity.filter(kind='assignees_changed').count(), 1)
        apply_roadmap(self.repo, ROADMAP)
        self.assertEqual(self.task.assignments.count(), 2)

    def test_assignment_validation_and_conflict(self):
        url = f'/api/work/tasks/{self.task.pk}/assign/'
        for ids in [[], [999999], [User.objects.create_user('customer').pk]]:
            self.assertEqual(self.client.post(url, {'assignee_ids': ids}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, {'assignee_ids': [self.staff.pk]}, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post(url, {'assignee_ids': [self.other.pk]}, content_type='application/json').status_code, 409)
        self.assertEqual(self.task.assignments.get().user, self.staff)

    def test_read_allowed_write_forbidden_for_ordinary_staff(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/api/work/tasks/?workspace=backlog').status_code, 200)
        self.assertEqual(self.client.get('/api/work/backlog-projects/').status_code, 200)
        self.assertEqual(self.client.post(f'/api/work/tasks/{self.task.pk}/assign/', {'assignee_ids': [self.staff.pk]}, content_type='application/json').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/api/work/backlog-projects/').status_code, 403)

    def test_checked_unassigned_task_leaves_backlog_without_approval(self):
        apply_roadmap(self.repo, ROADMAP.replace('[ ] Build Django', '[x] Build Django'))
        self.assertEqual(len(self.rows('workspace=backlog')), 1)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)
        self.assertFalse(self.task.assignments.exists())
        response = self.client.post(f'/api/work/tasks/{self.task.pk}/assign/', {'assignee_ids': [self.staff.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 409)
        apply_roadmap(self.repo, ROADMAP)
        self.assertEqual(len(self.rows('workspace=backlog')), 2)

    def test_project_status_reports_counts_without_configuration_controls(self):
        data = self.client.get('/api/work/backlog-projects/').json()
        self.assertEqual(data[0]['title'], self.project.title)
        self.assertEqual(data[0]['awaiting'], 2)
        self.assertNotIn('last_error', data[0])
