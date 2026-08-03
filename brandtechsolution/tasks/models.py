from django.conf import settings
from django.db import models
from django.utils import timezone


class Task(models.Model):
    """A unit of work an administrator hands to one or more staff members.

    The status ladder is deliberately narrow. Staff cannot reach DONE: they
    mark their own assignment complete, and the task moves itself to IN_REVIEW
    once every assignee has done so. Only a manage_tasks holder approves it to
    DONE or sends it back. If staff could close their own work there would be
    nothing left to review, which is the whole point of the section.
    """

    OPEN = "open"
    IN_REVIEW = "in_review"
    DONE = "done"

    STATUS_CHOICES = [
        (OPEN, "Open"),
        (IN_REVIEW, "In review"),
        (DONE, "Done"),
    ]

    # Stored as integers so "most urgent first" is a plain database sort.
    # A CharField would order alphabetically - high, low, normal, urgent -
    # which is meaningless, and would need a CASE expression on every query.
    LOW, NORMAL, HIGH, URGENT = 1, 2, 3, 4
    PRIORITY_CHOICES = [
        (LOW, "Low"),
        (NORMAL, "Normal"),
        (HIGH, "High"),
        (URGENT, "Urgent"),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=OPEN, db_index=True
    )
    priority = models.PositiveSmallIntegerField(
        choices=PRIORITY_CHOICES, default=NORMAL
    )
    due_date = models.DateField(null=True, blank=True)

    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TaskAssignment",
        related_name="assigned_tasks",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="tasks_created",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # nulls_last is spelled out because the backends disagree: Postgres
        # sorts NULLs last on ASC, SQLite sorts them first. Without this a
        # task with no due date would head the list on the dev database and
        # trail it in production, for the same query.
        ordering = [
            models.F("priority").desc(),
            models.F("due_date").asc(nulls_last=True),
            "-created_at",
        ]
        default_permissions = ()

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        if self.due_date is None or self.status == self.DONE:
            return False
        return self.due_date < timezone.localdate()

    def refresh_review_state(self):
        """Move between OPEN and IN_REVIEW to match the assignments.

        Called after any change to who is assigned or what they have marked.
        Centralised here so the rule holds however the change arrived - an
        assignee completing their part, an administrator editing the assignee
        list, or a person being unassigned mid-flight.

        A task with no assignees never reaches IN_REVIEW: "every assignee is
        finished" is vacuously true of an empty set, and auto-submitting an
        unassigned task the moment it was created would be nonsense.

        Returns the new status if it changed, otherwise None, so callers can
        decide whether to write an activity entry and notify.
        """
        if self.status == self.DONE:
            return None

        # Queried through TaskAssignment rather than self.assignments, which
        # would be wrong here. The viewset prefetches assignments, and a
        # related manager backed by a prefetch cache answers .count() from
        # that cache - so straight after an edit this method would read the
        # assignee list as it was BEFORE the edit and decide against a
        # transition that was due. Going to the table is immune to whatever
        # the caller happens to have cached on the instance.
        rows = TaskAssignment.objects.filter(task=self)
        total = rows.count()
        done = rows.filter(completed_at__isnull=False).count() if total else 0

        should_review = total > 0 and done == total

        if should_review and self.status != self.IN_REVIEW:
            self.status = self.IN_REVIEW
            self.submitted_at = timezone.now()
            self.save(update_fields=["status", "submitted_at", "updated_at"])
            return self.IN_REVIEW

        if not should_review and self.status == self.IN_REVIEW:
            self.status = self.OPEN
            self.submitted_at = None
            self.save(update_fields=["status", "submitted_at", "updated_at"])
            return self.OPEN

        return None


class TaskAssignment(models.Model):
    """One person's share of a task.

    The through model exists so completion is tracked per person rather than
    per task: with several people on a job, one of them finishing says nothing
    about whether the job is finished.
    """

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="assignments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_assignments",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["user__username"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["task", "user"], name="unique_task_assignee"
            ),
        ]

    def __str__(self):
        return f"{self.user} on {self.task}"


class TaskActivity(models.Model):
    """Append-only timeline: comments and status changes in one stream.

    Both live in one table because the UI shows one thread - a rejection
    reason only makes sense next to the submission it answers. `body` is
    rendered when the row is written, following the same rule as
    staff.AuditEntry.summary, so an entry still reads correctly after the
    user it names is deleted.
    """

    COMMENT = "comment"

    KIND_CHOICES = [
        (COMMENT, "Comment"),
        ("created", "Task created"),
        ("edited", "Task edited"),
        ("assignees_changed", "Assignees changed"),
        ("marked_done", "Assignee marked their part done"),
        ("marked_undone", "Assignee reopened their part"),
        ("submitted", "Submitted for review"),
        ("approved", "Approved"),
        ("reopened", "Sent back for more work"),
    ]

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="activity"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="task_activity",
    )
    # Denormalised so the timeline still names the actor after the account is
    # deleted and the SET_NULL above has fired.
    actor_name = models.CharField(max_length=150, blank=True, default="")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, db_index=True)
    body = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "task activity"
        default_permissions = ()

    def __str__(self):
        return f"{self.get_kind_display()} on {self.task_id}"
