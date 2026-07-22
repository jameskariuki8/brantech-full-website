from .models import AuditEntry


def record(actor, action, summary, target_user=None, target_group=None, detail=None):
    """Write one audit entry.

    Call inside the same transaction as the change being recorded, so an entry
    is never written for a change that rolled back.
    """
    return AuditEntry.objects.create(
        actor=actor,
        action=action,
        summary=summary,
        target_user=target_user,
        target_group=target_group,
        detail=detail or {},
    )
