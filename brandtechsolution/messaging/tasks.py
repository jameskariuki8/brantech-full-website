"""Celery tasks for bulk email delivery."""
import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(name='messaging.process_email_outbox')
def process_email_outbox_task():
    """Drain one batch of the email outbox.

    Replaces the compose service that ran
    `while true; do python manage.py process_email_outbox; sleep 60; done`.

    Deliberately calls the management command rather than reimplementing it:
    the claim-token protocol in process_email_outbox.py (claim pending rows
    under a token, release anything still 'sending' after
    OUTBOX_STALE_CLAIM_MINUTES) is what makes concurrent runs safe, and it is
    the one piece of this system that must not have a second implementation.
    The command remains runnable by hand, which is how you drain the queue
    without a worker.

    Not retried: a failed batch leaves its recipients claimed, the stale-claim
    release returns them to 'pending', and the next Beat tick picks them up.
    Retrying would only race the next tick for the same rows.
    """
    call_command('process_email_outbox', verbosity=0)
    return {'status': 'ok'}
