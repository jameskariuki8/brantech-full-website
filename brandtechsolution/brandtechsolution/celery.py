"""Celery application for the Teklora stack.

Background work previously ran either inline in a request -- the editorial
pipeline held an HTTP connection open for roughly three minutes, which
Cloudflare cut off at 100s with a 524 -- or in a `while true; sleep 60`
container for the email outbox. Both now run here.

Task discovery is autodiscover_tasks(), so every app's tasks.py is picked up
without being listed twice.
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "brandtechsolution.settings")

app = Celery("brandtechsolution")

# All CELERY_* settings live in Django settings, sourced from AppSettings.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    """Register the recurring jobs.

    Declared in code rather than via django-celery-beat's database scheduler:
    the schedule is fixed, and keeping it here means a fresh deployment starts
    processing the outbox without anyone opening the admin to create rows.
    """
    from django.conf import settings

    # Imported inside the handler, not at module scope: this module is imported
    # from brandtechsolution/__init__.py, which runs before django.setup(), and
    # these task modules import models.
    from brand.tasks import sync_github_task
    from editorial.tasks import release_stale_pipeline_runs_task
    from messaging.tasks import process_email_outbox_task

    sender.add_periodic_task(
        settings.BEAT_OUTBOX_INTERVAL,
        process_email_outbox_task.s(),
        name="drain the email outbox",
        # A late outbox run is worthless -- the next tick does the same work --
        # so drop any tick that piles up behind a slow run instead of queueing it.
        options={"expires": settings.BEAT_OUTBOX_INTERVAL},
    )

    sender.add_periodic_task(
        settings.BEAT_GITHUB_SYNC_INTERVAL,
        sync_github_task.s(),
        name="sync GitHub projects",
        options={"expires": settings.BEAT_GITHUB_SYNC_INTERVAL},
    )

    # Overnight, off the back of the working day in EAT.
    sender.add_periodic_task(
        crontab(hour=2, minute=30),
        release_stale_pipeline_runs_task.s(),
        name="fail pipeline runs abandoned by a dead worker",
    )
