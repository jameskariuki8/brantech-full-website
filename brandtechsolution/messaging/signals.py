"""Keep Contacts filled from the places people leave an address.

A failure here must never cost the visitor their inquiry or booking, so
each hook runs in its own savepoint and only logs what goes wrong.
"""

import logging

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from appointments.models import Appointment

from .contacts import remember
from .models import Inquiry

logger = logging.getLogger(__name__)


def _remember_safely(*args, **kwargs):
    try:
        with transaction.atomic():
            remember(*args, **kwargs)
    except Exception:
        logger.exception("Could not record contact %s", args[0] if args else "")


@receiver(post_save, sender=Inquiry, dispatch_uid="contact_from_inquiry")
def contact_from_inquiry(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        _remember_safely(instance.email, instance.name, instance.phone, source="inquiry")


@receiver(post_save, sender=Appointment, dispatch_uid="contact_from_appointment")
def contact_from_appointment(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        _remember_safely(instance.email, instance.full_name, instance.phone, source="appointment")


@receiver(post_save, sender=User, dispatch_uid="contact_from_account")
def contact_from_account(sender, instance, raw=False, update_fields=None, **kwargs):
    # Customers only; staff are reached through the panel. Logging in saves
    # last_login alone, which is no reason to look.
    if raw or instance.is_staff or not instance.email:
        return
    if update_fields is not None and set(update_fields) <= {"last_login"}:
        return
    _remember_safely(instance.email, instance.get_full_name(), source="account")
