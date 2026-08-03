from django.contrib.auth.models import Group, Permission, User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from tasks.models import Task, TaskActivity, TaskAssignment


def capability(codename):
    return Permission.objects.get(
        codename=codename, content_type__app_label="staff"
    )


def make_staff(username, capabilities=(), email=""):
    user = User.objects.create_user(
        username=username, password="pw", is_staff=True, email=email
    )
    if capabilities:
        group = Group.objects.create(name=f"{username}-role")
        group.permissions.set([capability(c) for c in capabilities])
        user.groups.add(group)
    return user


class ReviewLadderTest(TestCase):
    """The status ladder is the point of the feature: staff cannot reach DONE."""

    def setUp(self):
        self.admin = make_staff("admin", ["manage_tasks"], "admin@example.com")
        self.alice = make_staff("alice")
        self.bob = make_staff("bob")
        self.task = Task.objects.create(title="Ship the thing", created_by=self.admin)
        TaskAssignment.objects.create(task=self.task, user=self.alice)
        TaskAssignment.objects.create(task=self.task, user=self.bob)

    def test_one_of_two_finishing_does_not_submit(self):
        self.client.force_login(self.alice)
        response = self.client.post(f"/api/work/tasks/{self.task.pk}/complete/")

        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)

    def test_last_assignee_finishing_submits_for_review(self):
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            self.client.post(f"/api/work/tasks/{self.task.pk}/complete/")

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.IN_REVIEW)
        self.assertIsNotNone(self.task.submitted_at)

    def test_submission_emails_the_reviewers(self):
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            self.client.post(f"/api/work/tasks/{self.task.pk}/complete/")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].recipients(), ["admin@example.com"])
        self.assertIn("Ship the thing", mail.outbox[0].subject)

    def test_staff_cannot_approve_their_own_work(self):
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            self.client.post(f"/api/work/tasks/{self.task.pk}/complete/")

        self.client.force_login(self.alice)
        response = self.client.post(f"/api/work/tasks/{self.task.pk}/approve/")

        self.assertEqual(response.status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.IN_REVIEW)

    def test_admin_approves(self):
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            self.client.post(f"/api/work/tasks/{self.task.pk}/complete/")

        self.client.force_login(self.admin)
        response = self.client.post(f"/api/work/tasks/{self.task.pk}/approve/")

        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.DONE)
        self.assertIsNotNone(self.task.closed_at)

    def test_approve_rejects_a_task_not_in_review(self):
        self.client.force_login(self.admin)
        response = self.client.post(f"/api/work/tasks/{self.task.pk}/approve/")

        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)

    def test_one_assignee_undoing_pulls_the_task_back_out_of_review(self):
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            self.client.post(f"/api/work/tasks/{self.task.pk}/complete/")

        self.client.force_login(self.bob)
        self.client.post(f"/api/work/tasks/{self.task.pk}/uncomplete/")

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)
        self.assertIsNone(self.task.submitted_at)


class ReopenTest(TestCase):
    def setUp(self):
        self.admin = make_staff("admin", ["manage_tasks"])
        self.alice = make_staff("alice")
        self.task = Task.objects.create(title="Redo this", created_by=self.admin)
        TaskAssignment.objects.create(
            task=self.task, user=self.alice, completed_at=timezone.now()
        )
        self.task.refresh_review_state()

    def test_reopen_requires_a_reason(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            f"/api/work/tasks/{self.task.pk}/reopen/",
            {"reason": "   "},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.IN_REVIEW)

    def test_reopen_clears_every_completion(self):
        """Otherwise the task bounces straight back into review untouched."""
        self.client.force_login(self.admin)
        response = self.client.post(
            f"/api/work/tasks/{self.task.pk}/reopen/",
            {"reason": "The header is still wrong"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)
        self.assertFalse(
            self.task.assignments.filter(completed_at__isnull=False).exists()
        )

    def test_reason_lands_in_the_timeline(self):
        self.client.force_login(self.admin)
        self.client.post(
            f"/api/work/tasks/{self.task.pk}/reopen/",
            {"reason": "The header is still wrong"},
            content_type="application/json",
        )

        entry = self.task.activity.filter(kind="reopened").get()
        self.assertEqual(entry.body, "The header is still wrong")

    def test_staff_cannot_reopen(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            f"/api/work/tasks/{self.task.pk}/reopen/",
            {"reason": "let me at it"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)


class BoundaryTest(TestCase):
    """Read wide, write narrow."""

    def setUp(self):
        self.admin = make_staff("admin", ["manage_tasks"])
        self.alice = make_staff("alice")
        self.bob = make_staff("bob")
        self.outsider = User.objects.create_user(username="customer", password="pw")
        self.task = Task.objects.create(title="Visible", created_by=self.admin)
        TaskAssignment.objects.create(task=self.task, user=self.alice)

    def test_any_staff_member_sees_the_whole_board(self):
        self.client.force_login(self.bob)
        response = self.client.get("/api/work/tasks/")

        self.assertEqual(response.status_code, 200)
        titles = [row["title"] for row in response.json()["results"]]
        self.assertIn("Visible", titles)

    def test_non_staff_account_is_refused(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get("/api/work/tasks/").status_code, 403)

    def test_anonymous_is_refused(self):
        self.assertEqual(self.client.get("/api/work/tasks/").status_code, 403)

    def test_staff_cannot_create_a_task(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            "/api/work/tasks/",
            {"title": "Mine now", "assignee_ids": []},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Task.objects.filter(title="Mine now").exists())

    def test_staff_cannot_complete_someone_elses_part(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            f"/api/work/tasks/{self.task.pk}/complete/",
            {"assignee_id": self.alice.pk},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            self.task.assignments.filter(completed_at__isnull=False).exists()
        )

    def test_unassigned_staff_cannot_complete_for_themselves(self):
        self.client.force_login(self.bob)
        response = self.client.post(f"/api/work/tasks/{self.task.pk}/complete/")

        self.assertEqual(response.status_code, 400)

    def test_admin_may_complete_on_someone_else_s_behalf(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            f"/api/work/tasks/{self.task.pk}/complete/",
            {"assignee_id": self.alice.pk},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.IN_REVIEW)

    def test_status_is_not_writable_through_a_patch(self):
        """The ladder must not be skippable by an administrator either.

        Writing status directly would leave the task DONE while its
        assignments still read as outstanding.
        """
        self.client.force_login(self.admin)
        response = self.client.patch(
            f"/api/work/tasks/{self.task.pk}/",
            {"status": "done"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)

    def test_completion_is_refused_once_the_task_is_approved(self):
        self.client.force_login(self.admin)
        self.client.post(
            f"/api/work/tasks/{self.task.pk}/complete/",
            {"assignee_id": self.alice.pk},
            content_type="application/json",
        )
        self.client.post(f"/api/work/tasks/{self.task.pk}/approve/")

        self.client.force_login(self.alice)
        response = self.client.post(f"/api/work/tasks/{self.task.pk}/uncomplete/")

        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.DONE)


class AssignmentEditingTest(TestCase):
    def setUp(self):
        self.admin = make_staff("admin", ["manage_tasks"])
        self.alice = make_staff("alice")
        self.bob = make_staff("bob")

    def test_adding_an_assignee_preserves_existing_completions(self):
        """A delete-and-recreate would silently undo everyone's work."""
        task = Task.objects.create(title="Shared", created_by=self.admin)
        TaskAssignment.objects.create(
            task=task, user=self.alice, completed_at=timezone.now()
        )

        self.client.force_login(self.admin)
        response = self.client.patch(
            f"/api/work/tasks/{task.pk}/",
            {"assignee_ids": [self.alice.pk, self.bob.pk]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            task.assignments.get(user=self.alice).completed_at
        )

    def test_adding_an_assignee_pulls_a_reviewed_task_back_open(self):
        task = Task.objects.create(title="Shared", created_by=self.admin)
        TaskAssignment.objects.create(
            task=task, user=self.alice, completed_at=timezone.now()
        )
        task.refresh_review_state()
        self.assertEqual(task.status, Task.IN_REVIEW)

        self.client.force_login(self.admin)
        self.client.patch(
            f"/api/work/tasks/{task.pk}/",
            {"assignee_ids": [self.alice.pk, self.bob.pk]},
            content_type="application/json",
        )

        task.refresh_from_db()
        self.assertEqual(task.status, Task.OPEN)

    def test_removing_the_last_unfinished_assignee_submits_the_task(self):
        task = Task.objects.create(title="Shared", created_by=self.admin)
        TaskAssignment.objects.create(
            task=task, user=self.alice, completed_at=timezone.now()
        )
        TaskAssignment.objects.create(task=task, user=self.bob)

        self.client.force_login(self.admin)
        self.client.patch(
            f"/api/work/tasks/{task.pk}/",
            {"assignee_ids": [self.alice.pk]},
            content_type="application/json",
        )

        task.refresh_from_db()
        self.assertEqual(task.status, Task.IN_REVIEW)

    def test_an_unassigned_task_never_submits_itself(self):
        """All-done is vacuously true of an empty set; guard against it."""
        task = Task.objects.create(title="Nobody's", created_by=self.admin)

        self.assertIsNone(task.refresh_review_state())
        self.assertEqual(task.status, Task.OPEN)

    def test_customers_cannot_be_assigned_work(self):
        User.objects.create_user(username="customer", password="pw")
        customer = User.objects.get(username="customer")

        self.client.force_login(self.admin)
        response = self.client.post(
            "/api/work/tasks/",
            {"title": "Nope", "assignee_ids": [customer.pk]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)


class ActivityTest(TestCase):
    def setUp(self):
        self.admin = make_staff("admin", ["manage_tasks"])
        self.alice = make_staff("alice")
        self.task = Task.objects.create(title="Talk about it", created_by=self.admin)
        TaskAssignment.objects.create(task=self.task, user=self.alice)

    def test_any_staff_member_may_comment(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            f"/api/work/tasks/{self.task.pk}/activity/",
            {"body": "Blocked on the API key"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            self.task.activity.filter(
                kind=TaskActivity.COMMENT, body="Blocked on the API key"
            ).exists()
        )

    def test_empty_comment_is_refused(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            f"/api/work/tasks/{self.task.pk}/activity/",
            {"body": "   "},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_timeline_survives_the_actor_being_deleted(self):
        self.client.force_login(self.alice)
        self.client.post(
            f"/api/work/tasks/{self.task.pk}/activity/",
            {"body": "still here"},
            content_type="application/json",
        )
        self.alice.delete()

        entry = self.task.activity.get(kind=TaskActivity.COMMENT)
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_name, "alice")


class SummaryTest(TestCase):
    def setUp(self):
        self.admin = make_staff("admin", ["manage_tasks"])
        self.alice = make_staff("alice")

    def test_review_count_is_hidden_from_those_who_cannot_act_on_it(self):
        task = Task.objects.create(title="Waiting", created_by=self.admin)
        TaskAssignment.objects.create(
            task=task, user=self.alice, completed_at=timezone.now()
        )
        task.refresh_review_state()

        self.client.force_login(self.alice)
        payload = self.client.get("/api/work/summary/").json()

        self.assertEqual(payload["needs_review"], 0)
        self.assertFalse(payload["can_manage"])

        self.client.force_login(self.admin)
        payload = self.client.get("/api/work/summary/").json()

        self.assertEqual(payload["needs_review"], 1)
        self.assertTrue(payload["can_manage"])

    def test_my_open_counts_only_unfinished_assignments(self):
        done = Task.objects.create(title="Finished", created_by=self.admin)
        TaskAssignment.objects.create(
            task=done, user=self.alice, completed_at=timezone.now()
        )
        open_task = Task.objects.create(title="Outstanding", created_by=self.admin)
        TaskAssignment.objects.create(task=open_task, user=self.alice)

        self.client.force_login(self.alice)
        payload = self.client.get("/api/work/summary/").json()

        self.assertEqual(payload["my_open"], 1)
