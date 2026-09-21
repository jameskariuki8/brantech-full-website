"""Telling someone when an agent stops working.

Failing loudly is only loud if somebody hears it. A failed run visible only on
/editorial/dashboard/ is visible only to whoever happens to open it, which for
an overnight Beat run is nobody.

This is the first health alert in the codebase -- the six existing send_mail
sites are all transactional notices. Recipients come from the same
capability-addressed helper the approval workflow already uses, so who gets
paged changes by ticking a box in the panel rather than by editing an
environment variable.
"""
import logging

from django.db import transaction
from django.utils import timezone

from brandtechsolution.config import config

logger = logging.getLogger(__name__)

ALERT_CAPABILITY = "receive_alerts"

FAILURE_ACCENT = "#F87171"
RECOVERY_ACCENT = "#00FF94"


def alert_recipients():
    """Staff who hold `receive_alerts`.

    A codename of its own rather than a reuse of manage_staff: the people who
    should be woken by a dead pipeline are not necessarily the people who
    administer accounts, and conflating them would make giving up an unrelated
    permission the only way to stop being paged.
    """
    from staff.emails import capability_holder_emails

    return capability_holder_emails(ALERT_CAPABILITY)


def _send(subject, context, recipients):
    from brandtechsolution.mail import send_mail_html

    return send_mail_html(
        subject=subject,
        template="mail/agent_alert.html",
        context=context,
        recipients=recipients,
        # Never silent. A swallowed alert is the failure going quiet again by
        # another route, which is the exact thing this module exists to stop.
        fail_silently=False,
    )


def record_failure(agent, error, *, provider="", model="", run_id=None):
    """Note that `agent` failed, and alert if this is a state change.

    Returns True when an alert was sent. The first failure of a run of them
    sends; the rest are counted and suppressed until the error class changes or
    the agent recovers.
    """
    from ai_workflows.models import AgentHealth

    error_class = type(error).__name__
    now = timezone.now()

    with transaction.atomic():
        health, _ = AgentHealth.objects.select_for_update().get_or_create(agent=agent)

        # Same outage continuing: count it and say nothing.
        already_alerting = health.is_failing and health.error_class == error_class
        health.status = AgentHealth.FAILING
        health.error_class = error_class
        health.error_message = str(error)[:2000]
        health.last_failure_at = now
        if health.failing_since is None:
            health.failing_since = now

        if already_alerting:
            health.suppressed_since_alert += 1
            health.save()
            return False

        # A new outage, or a different kind of failure during an existing one.
        suppressed = health.suppressed_since_alert
        health.suppressed_since_alert = 0
        health.last_alert_at = now
        health.save()

    recipients = alert_recipients()
    if not recipients:
        logger.error(
            "[alerts] %s is failing (%s) and nobody holds %s, so nobody was told",
            agent, error_class, ALERT_CAPABILITY,
        )
        return False

    context = {
        "subject": f"[Teklora] {agent} is failing",
        "agent": agent,
        "accent": FAILURE_ACCENT,
        "header_label": "Agent failure",
        "capability": ALERT_CAPABILITY,
        "recovered": False,
        "error_class": error_class,
        "error_message": str(error)[:500],
        "started_at": timezone.localtime(health.failing_since).strftime("%Y-%m-%d %H:%M %Z"),
        "provider": provider,
        "model": model,
        "run_id": run_id,
        "suppressed": suppressed or None,
        "action_url": f"{config.site_base_url}/editorial/dashboard/",
        "action_label": "Open the dashboard",
    }

    try:
        _send(context["subject"], context, recipients)
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
        logger.exception("[alerts] could not send the failure alert for %s", agent)
        AgentHealth.objects.filter(pk=health.pk).update(
            last_alert_error=f"{type(exc).__name__}: {exc}"[:500]
        )
        return False

    AgentHealth.objects.filter(pk=health.pk).update(last_alert_error="")
    return True


def record_success(agent):
    """Note that `agent` worked, and alert once if it had been failing.

    A recovery message matters as much as the failure one: without it the only
    way to know an outage ended is to notice that the alerts stopped, which is
    indistinguishable from the alerting itself having broken.
    """
    from ai_workflows.models import AgentHealth

    with transaction.atomic():
        health = (
            AgentHealth.objects.select_for_update().filter(agent=agent).first()
        )
        if health is None:
            AgentHealth.objects.create(agent=agent, status=AgentHealth.HEALTHY)
            return False

        if not health.is_failing:
            return False

        failing_since = health.failing_since
        suppressed = health.suppressed_since_alert

        health.status = AgentHealth.HEALTHY
        health.error_class = ""
        health.error_message = ""
        health.failing_since = None
        health.suppressed_since_alert = 0
        health.last_alert_at = timezone.now()
        health.save()

    recipients = alert_recipients()
    if not recipients:
        return False

    context = {
        "subject": f"[Teklora] {agent} is working again",
        "agent": agent,
        "accent": RECOVERY_ACCENT,
        "header_label": "Recovered",
        "capability": ALERT_CAPABILITY,
        "recovered": True,
        "started_at": (
            timezone.localtime(failing_since).strftime("%Y-%m-%d %H:%M %Z")
            if failing_since else ""
        ),
        "suppressed": suppressed or None,
        "action_url": f"{config.site_base_url}/editorial/dashboard/",
        "action_label": "Open the dashboard",
    }

    try:
        _send(context["subject"], context, recipients)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[alerts] could not send the recovery alert for %s", agent)
        AgentHealth.objects.filter(agent=agent).update(
            last_alert_error=f"{type(exc).__name__}: {exc}"[:500]
        )
        return False

    return True
