import logging

from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.core.mail import send_mail
from django.db.models import Q

logger = logging.getLogger(__name__)


def users_with_capability(codename):
    """Active staff who hold `codename`, by role, direct grant or superuser.

    Django can answer "does this user have the permission" but not "who has
    it", so the three routes are spelled out. distinct() matters: a user in
    two roles that both carry the capability would otherwise appear twice and
    be mailed twice.
    """
    permission = Permission.objects.filter(
        codename=codename, content_type__app_label="staff"
    ).first()
    if permission is None:
        # The capability row is created by post_migrate. Before that has run
        # nobody can hold it, and Q(groups__permissions=None) would match
        # every user with no group permissions at all - mailing the wrong
        # people rather than none.
        return User.objects.filter(is_active=True, is_staff=True, is_superuser=True)

    return User.objects.filter(
        Q(is_superuser=True)
        | Q(groups__permissions=permission)
        | Q(user_permissions=permission),
        is_active=True,
        is_staff=True,
    ).distinct()


def notify_review_ready(task, request=None):
    """Tell the administrators a task is waiting for review.

    Never raises. The panel's "Needs review" queue is the real signal and is
    derived from the task's status, so a mail server problem must not roll
    back the submission that a staff member has legitimately made.
    """
    recipients = [
        u.email
        for u in users_with_capability("manage_tasks").exclude(email="")
    ]
    if not recipients:
        return 0

    # Deep-links to the section rather than the panel's default Overview.
    # The version 2 shell reads ?section= on load, so this lands the reviewer
    # on the board instead of making them hunt for it from the dashboard.
    path = "/admin-panel/?section=tasks"
    url = request.build_absolute_uri(path) if request else path
    who = ", ".join(sorted(a.user.username for a in task.assignments.all()))

    try:
        send_mail(
            subject=f"[Teklora] Ready for review: {task.title}",
            message=(
                f"{who or 'Nobody'} finished work on \"{task.title}\".\n\n"
                f"Priority: {task.get_priority_display()}\n"
                f"Due: {task.due_date or 'no due date'}\n\n"
                f"Review it in the panel:\n{url}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
        return len(recipients)
    except Exception:
        logger.exception("Could not send review notification for task %s", task.pk)
        return 0
