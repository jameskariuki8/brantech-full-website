"""Rules shared by the campaign API and the outbox sender.

A template is the email; a campaign is who gets it, from which address,
and when. The campaign carries a copy of its template's subject and body so
the sender never reads a template that someone is still editing.
"""

import email.utils

from django.conf import settings

from staff.handles import SHARED_MAILBOXES, mailbox_address

from . import quota
from .models import Campaign, CampaignRecipient, MailSettings

ORG_NAME = "Teklora"
ACTIVE_STATUSES = ("queued", "sending", "paused")


def sender_choices(user):
    """Addresses this person may send a campaign from: the shared
    mailboxes, plus their own work address once they have one."""
    choices = [
        {"value": box, "address": mailbox_address(box), "label": ORG_NAME}
        for box in SHARED_MAILBOXES
    ]
    if user is not None and "@" not in user.username:
        choices.append({
            "value": user.username,
            "address": mailbox_address(user.username),
            "label": user.get_full_name() or user.username,
        })
    return choices


def allowed_sender(user, value, campaign=None):
    if value in SHARED_MAILBOXES:
        return True
    # A campaign keeps the author's address it was given, even when someone
    # else later edits it.
    if campaign is not None and value == campaign.from_mailbox:
        return True
    return user is not None and value == user.username and "@" not in user.username


def from_header(campaign):
    box = campaign.from_mailbox
    if not box:
        return settings.DEFAULT_FROM_EMAIL
    if box in SHARED_MAILBOXES:
        name = ORG_NAME
    else:
        author = campaign.created_by
        name = (author.get_full_name() if author else "") or ORG_NAME
    return email.utils.formataddr((name, mailbox_address(box)))


def reply_to(campaign):
    return [mailbox_address(campaign.from_mailbox)] if campaign.from_mailbox else []


def copy_template(campaign, template):
    campaign.template = template
    campaign.subject = template.subject
    campaign.body_source = template.body_source
    campaign.body_html = template.body_html


def refresh_drafts(template):
    """Carry a template edit into the drafts that use it."""
    Campaign.objects.filter(template=template, status="draft").update(
        subject=template.subject,
        body_source=template.body_source,
        body_html=template.body_html,
    )


def committed(exclude=None):
    """Recipients already promised to other campaigns that have not been
    sent yet: queueing a new one must leave room for them."""
    qs = CampaignRecipient.objects.filter(
        campaign__status__in=ACTIVE_STATUSES, status__in=("pending", "sending"),
    )
    if exclude is not None:
        qs = qs.exclude(campaign=exclude)
    return qs.count()


def month_headroom(exclude=None):
    cap = MailSettings.load().monthly_cap
    return max(cap - quota.used_this_month() - committed(exclude), 0)


def cap_note(cap):
    return (
        f"Paused automatically: the company reached its monthly cap of {cap} "
        "recipients. Raise it under Mail, Sending limits, or resume after the 1st."
    )
