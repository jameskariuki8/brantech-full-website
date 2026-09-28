"""Sending limits for staff mail.

Everything counts recipients, not messages: one email to 40 people is 40,
which is how Mailgun bills and how a domain earns a spam reputation. A
person's daily limit covers everything they send, from their own address or
a shared one, and resets at local midnight. The monthly cap covers the whole
company, campaigns included, so staff mail cannot eat the plan's allowance
out from under a scheduled campaign unnoticed.
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

from staff.emails import capability_holder_emails
from staff.models import StaffProfile

from .models import CampaignRecipient, MailMessage, MailSettings

logger = logging.getLogger(__name__)


class QuotaExceeded(Exception):
    pass


def _day_start(now=None):
    return timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now=None):
    return _day_start(now).replace(day=1)


def _recipients(queryset):
    return sum(len(to or []) + len(cc or []) for to, cc in queryset.values_list("to", "cc"))


def used_today(user):
    return _recipients(MailMessage.objects.filter(
        direction="out", status="sent", sent_by=user, created_at__gte=_day_start(),
    ))


def used_this_month():
    start = _month_start()
    staff_mail = _recipients(MailMessage.objects.filter(
        direction="out", status="sent", created_at__gte=start,
    ))
    campaigns = CampaignRecipient.objects.filter(status="sent", sent_at__gte=start).count()
    return staff_mail + campaigns


def limit_for(user, mail_settings=None):
    profile = StaffProfile.objects.filter(user=user).first()
    if profile is not None and profile.daily_mail_limit is not None:
        return profile.daily_mail_limit
    return (mail_settings or MailSettings.load()).default_daily_limit


def status(user):
    """What the compose screen shows: used, limit and when it resets."""
    limit = limit_for(user)
    used = used_today(user)
    return {
        "used": used,
        "limit": limit,
        "remaining": max(limit - used, 0),
        "resets_at": _day_start() + timedelta(days=1),
    }


def check(user, recipient_count):
    """Raise QuotaExceeded when sending to recipient_count more people would
    break the person's daily limit or the company's monthly cap. Call it
    with MailSettings locked (see lock()) so two sends cannot both pass."""
    mail_settings = MailSettings.load()
    limit = limit_for(user, mail_settings)
    if limit == 0:
        raise QuotaExceeded("Sending is suspended for your account. Ask an administrator.")
    used = used_today(user)
    if used + recipient_count > limit:
        _notify_admins(user, used, limit)
        left = max(limit - used, 0)
        raise QuotaExceeded(
            f"This message has {recipient_count} recipient"
            f"{'' if recipient_count == 1 else 's'}, and you have {left} of your "
            f"{limit} left today. The count resets at midnight."
        )
    month = used_this_month()
    if month + recipient_count > mail_settings.monthly_cap:
        raise QuotaExceeded(
            f"The company has used {month} of its {mail_settings.monthly_cap} "
            "recipients this month. Ask an administrator."
        )


def lock():
    """Serialise sends: the caller holds this row until its transaction ends."""
    MailSettings.load()
    return MailSettings.objects.select_for_update().get(pk=1)


def _notify_admins(user, used, limit):
    # Once per person per day, or a retrying user would mail the admins
    # every click - and each notice is itself a recipient off the quota.
    key = f"mail-limit-notice:{user.pk}:{_day_start().date()}"
    if not cache.add(key, 1, timeout=60 * 60 * 25):
        return
    recipients = [e for e in capability_holder_emails("manage_mail_limits") if e != user.email]
    if not recipients:
        return
    name = user.get_full_name() or user.username
    try:
        send_mail(
            subject=f"{name} reached their daily mail limit",
            message=(
                f"{name} ({user.username}) has sent to {used} of their {limit} "
                "recipients today and was stopped from sending more.\n\n"
                "Limits are set in the panel under Mail, Sending limits."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        logger.exception("Could not notify admins that %s hit their mail limit", user)
