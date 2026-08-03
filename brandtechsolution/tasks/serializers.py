from django.contrib.auth.models import User
from rest_framework import serializers

from .models import Task, TaskActivity, TaskAssignment


def staff_queryset():
    """Who may be assigned work.

    /signup/ is public, so User at large includes customers. Assigning a task
    to one of them would put it in a dashboard they cannot open.
    """
    return User.objects.filter(is_staff=True, is_active=True)


class TaskActivitySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = TaskActivity
        fields = ["id", "kind", "kind_display", "body", "actor_name", "created_at"]
        read_only_fields = fields


class TaskAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    done = serializers.SerializerMethodField()

    class Meta:
        model = TaskAssignment
        fields = ["id", "username", "done", "completed_at"]
        read_only_fields = fields

    def get_done(self, obj):
        return obj.completed_at is not None


class TaskSerializer(serializers.ModelSerializer):
    # assignee_ids is the write path and is write_only so DRF never calls
    # get_attribute("assignee_ids") on a Task while rendering - no such
    # attribute exists and it would raise. The readable shape is `assignees`,
    # which carries each person's own completion state.
    assignee_ids = serializers.PrimaryKeyRelatedField(
        queryset=staff_queryset(), many=True, write_only=True, required=False
    )
    assignees = TaskAssignmentSerializer(
        source="assignments", many=True, read_only=True
    )

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(
        source="get_priority_display", read_only=True
    )
    is_overdue = serializers.BooleanField(read_only=True)
    created_by_name = serializers.SerializerMethodField()
    my_assignment = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "status", "status_display",
            "priority", "priority_display", "due_date", "is_overdue",
            "assignees", "assignee_ids", "created_by_name", "my_assignment",
            "comment_count", "created_at", "updated_at", "submitted_at",
            "closed_at",
        ]
        # status is absent from the writable set on purpose. It is moved only
        # by the complete/approve/reopen actions, each of which enforces its
        # own rule; leaving it writable here would let a PATCH from any
        # manage_tasks holder skip the ladder, and worse, would make the
        # per-assignee completion state and the task status disagree.
        read_only_fields = [
            "status", "created_at", "updated_at", "submitted_at", "closed_at",
        ]

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by else "system"

    def get_comment_count(self, obj):
        return sum(
            1 for a in obj.activity.all() if a.kind == TaskActivity.COMMENT
        )

    def get_my_assignment(self, obj):
        """This viewer's own share, or None if they are not assigned.

        Drives the "Mark my part done" button. Computed from the prefetched
        assignments rather than a fresh query so a list of 50 tasks does not
        issue 50 extra ones.
        """
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        for assignment in obj.assignments.all():
            if assignment.user_id == request.user.id:
                return {
                    "done": assignment.completed_at is not None,
                    "completed_at": assignment.completed_at,
                }
        return None

    def validate_title(self, value):
        title = value.strip()
        if not title:
            raise serializers.ValidationError("A task needs a title.")
        return title

    def _sync_assignees(self, task, users):
        """Replace the assignee list without disturbing who was already done.

        A plain delete-and-recreate would reset completed_at for everyone who
        stayed on the task, so adding a fifth person would silently undo four
        people's completions and bounce the task out of review.
        """
        wanted = {u.id for u in users}
        # Read from the table, not task.assignments, which may be answering
        # from a prefetch cache the viewset populated. See the note in
        # Task.refresh_review_state.
        rows = TaskAssignment.objects.filter(task=task)
        existing = set(rows.values_list("user_id", flat=True))

        rows.filter(user_id__in=existing - wanted).delete()
        TaskAssignment.objects.bulk_create(
            [TaskAssignment(task=task, user_id=uid) for uid in wanted - existing]
        )

    def create(self, validated_data):
        users = validated_data.pop("assignee_ids", [])
        task = Task.objects.create(**validated_data)
        self._sync_assignees(task, users)
        return task

    def update(self, instance, validated_data):
        users = validated_data.pop("assignee_ids", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if users is not None:
            self._sync_assignees(instance, users)
        return instance
