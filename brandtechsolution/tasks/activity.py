from .models import TaskActivity


def record(task, actor, kind, body=""):
    """Write one timeline entry.

    Call inside the same transaction as the change being recorded, so an
    entry is never left behind for a change that rolled back. Same rule as
    staff.audit.record.
    """
    return TaskActivity.objects.create(
        task=task,
        actor=actor,
        actor_name=getattr(actor, "username", "") or "system",
        kind=kind,
        body=body,
    )
