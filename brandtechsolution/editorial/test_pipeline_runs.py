"""The pipeline trigger queues work instead of running it in the request.

Running the cycle inline meant a roughly three-minute HTTP request. Behind the
Cloudflare tunnel that was cut off at 100s and the browser was handed a 524
HTML page where it expected JSON, while the work carried on to completion
invisibly. These tests pin the queue-and-poll behaviour that replaced it.
"""
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from editorial.models import EditorialArticle, EditorialPipelineRun


def publisher():
    user = User.objects.create_user("editor", password="pw", is_staff=True)
    group = Group.objects.create(name="publishers")
    group.permissions.set([
        Permission.objects.get(codename=c, content_type__app_label="staff")
        for c in ("manage_blog", "publish_blog")
    ])
    user.groups.add(group)
    return user


class TriggerTest(TestCase):
    def setUp(self):
        self.client.force_login(publisher())

    def test_trigger_returns_immediately_with_a_run_id(self):
        # captureOnCommitCallbacks: the view queues via transaction.on_commit
        # so the worker cannot see the task before the run row is committed,
        # and TestCase rolls back rather than committing.
        with mock.patch("editorial.views.run_editorial_pipeline_task") as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    "/editorial/api/run-pipeline/",
                    data="{}",
                    content_type="application/json",
                )

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertTrue(EditorialPipelineRun.objects.filter(pk=body["run_id"]).exists())
        task.delay.assert_called_once_with(body["run_id"])

    def test_the_run_records_who_started_it(self):
        with mock.patch("editorial.views.run_editorial_pipeline_task"):
            response = self.client.post("/editorial/api/run-pipeline/")

        run = EditorialPipelineRun.objects.get(pk=response.json()["run_id"])
        self.assertEqual(run.triggered_by.username, "editor")

    def test_a_second_run_is_refused_while_one_is_in_flight(self):
        """Two concurrent cycles would research and draft the same prioritised
        topics, doubling the model spend for duplicate output."""
        existing = EditorialPipelineRun.objects.create(status="running")

        with mock.patch("editorial.views.run_editorial_pipeline_task") as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post("/editorial/api/run-pipeline/")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["run_id"], existing.pk)
        task.delay.assert_not_called()
        self.assertEqual(EditorialPipelineRun.objects.count(), 1)

    def test_a_finished_run_does_not_block_the_next_one(self):
        EditorialPipelineRun.objects.create(status="success")

        with mock.patch("editorial.views.run_editorial_pipeline_task"):
            response = self.client.post("/editorial/api/run-pipeline/")

        self.assertEqual(response.status_code, 202)

    def test_limit_is_clamped(self):
        with mock.patch("editorial.views.run_editorial_pipeline_task"):
            response = self.client.post(
                "/editorial/api/run-pipeline/",
                data='{"limit": 500}',
                content_type="application/json",
            )

        run = EditorialPipelineRun.objects.get(pk=response.json()["run_id"])
        self.assertEqual(run.limit, 5)


class StatusPollTest(TestCase):
    def setUp(self):
        self.client.force_login(publisher())

    def test_progress_is_reported_while_running(self):
        run = EditorialPipelineRun.objects.create()
        run.mark_stage("writing")

        body = self.client.get(f"/editorial/api/pipeline-runs/{run.pk}/").json()

        self.assertEqual(body["status"], "running")
        self.assertEqual(body["stage"], "writing")
        self.assertEqual(body["stage_label"], "Drafting the article")
        self.assertEqual(body["stage_index"], 7)
        self.assertEqual(body["stage_total"], len(EditorialPipelineRun.STAGES))

    def test_articles_are_reported_once_the_run_succeeds(self):
        run = EditorialPipelineRun.objects.create(status="success")
        article = EditorialArticle.objects.create(title="Result", slug="result")
        run.articles.add(article)

        body = self.client.get(f"/editorial/api/pipeline-runs/{run.pk}/").json()

        self.assertEqual(body["articles_processed"], 1)
        self.assertEqual(body["articles"][0]["title"], "Result")

    def test_failure_reason_reaches_the_dashboard(self):
        run = EditorialPipelineRun.objects.create(status="failed", error="boom")

        body = self.client.get(f"/editorial/api/pipeline-runs/{run.pk}/").json()

        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["error"], "boom")


class TaskTest(TestCase):
    def test_the_task_records_success_and_its_articles(self):
        from editorial.tasks import run_editorial_pipeline_task

        run = EditorialPipelineRun.objects.create()
        article = EditorialArticle.objects.create(title="Made", slug="made")

        with mock.patch("editorial.orchestrator.EditorialPipelineOrchestrator") as orch:
            orch.return_value.run_full_autonomous_cycle.return_value = [article]
            run_editorial_pipeline_task(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, "success")
        self.assertIsNotNone(run.started_at)
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(list(run.articles.all()), [article])

    def test_a_crash_is_recorded_against_the_run(self):
        """Previously a mid-pipeline crash left no trace the dashboard could
        show -- the browser had already given up on the request."""
        from editorial.tasks import run_editorial_pipeline_task

        run = EditorialPipelineRun.objects.create()

        with mock.patch("editorial.orchestrator.EditorialPipelineOrchestrator") as orch:
            orch.return_value.run_full_autonomous_cycle.side_effect = RuntimeError("nope")
            with self.assertRaises(RuntimeError):
                run_editorial_pipeline_task(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("nope", run.error)
        self.assertIsNotNone(run.finished_at)

    def test_abandoned_runs_are_swept(self):
        from django.conf import settings
        from django.utils import timezone

        from editorial.tasks import release_stale_pipeline_runs_task

        stale = EditorialPipelineRun.objects.create(status="running")
        EditorialPipelineRun.objects.filter(pk=stale.pk).update(
            created_at=timezone.now()
            - timezone.timedelta(seconds=settings.CELERY_TASK_TIME_LIMIT * 3)
        )
        fresh = EditorialPipelineRun.objects.create(status="running")

        release_stale_pipeline_runs_task()

        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stale.status, "failed")
        self.assertEqual(fresh.status, "running")


class StageCallbackTest(TestCase):
    def test_the_orchestrator_reports_stages_to_its_run(self):
        """The callback is what turns a spinner into a progress bar."""
        run = EditorialPipelineRun.objects.create()
        seen = []

        run.mark_stage("discovery")
        seen.append(run.stage_index)
        run.mark_stage("handoff")
        seen.append(run.stage_index)

        self.assertEqual(seen, [1, len(EditorialPipelineRun.STAGES)])
        self.assertEqual(run.status, "running")
