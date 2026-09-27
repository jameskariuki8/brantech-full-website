from django.conf import settings
from django.db import models


class Inquiry(models.Model):
    STATUS_CHOICES = [
        ("new", "New"),
        ("read", "Read"),
        ("replied", "Replied"),
        ("archived", "Archived"),
    ]

    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True, default="")
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class InboundEmail(models.Model):
    STATUS_CHOICES = [
        ("received", "Received"),
        ("processed", "Processed"),
        ("archived", "Archived"),
    ]

    sender = models.EmailField()
    recipient = models.EmailField()
    subject = models.CharField(max_length=500, blank=True, default="")
    body_plain = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="")
    message_headers = models.JSONField(default=dict, blank=True)
    attachments_info = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="received")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "Inbound Email"
        verbose_name_plural = "Inbound Emails"

    def __str__(self):
        return f"From {self.sender}: {self.subject[:50]}"



class EmailTemplate(models.Model):
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=255)
    body_source = models.TextField(
        blank=True,
        default="",
        help_text="Authored HTML as edited. Sanitized but not CSS-inlined.",
    )
    body_html = models.TextField(help_text="HTML body. Supports {{ name }} and {{ unsubscribe_url }}.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Suppression(models.Model):
    REASON_CHOICES = [
        ("unsubscribed", "Unsubscribed"),
        ("bounced", "Bounced"),
        ("manual", "Manual"),
    ]
    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default="unsubscribed")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.email} ({self.reason})"


class Campaign(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("queued", "Queued"),
        ("sending", "Sending"),
        ("sent", "Sent"),
        ("paused", "Paused"),
        ("failed", "Failed"),
    ]
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=255)
    body_source = models.TextField(
        blank=True,
        default="",
        help_text="Authored HTML as edited. Sanitized but not CSS-inlined.",
    )
    body_html = models.TextField()
    template = models.ForeignKey(
        "EmailTemplate", null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    total = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class CampaignRecipient(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sending", "Sending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    ]
    campaign = models.ForeignKey(
        Campaign, related_name="recipients", on_delete=models.CASCADE
    )
    email = models.EmailField()
    name = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    VALIDATION_CHOICES = [
        ("unknown", "Not checked"),
        ("valid", "Valid"),
        ("invalid_syntax", "Malformed address"),
        ("invalid_domain", "Domain has no mail server"),
    ]
    validation_status = models.CharField(
        max_length=20, choices=VALIDATION_CHOICES, default="unknown"
    )
    # Set by the MX pass only. A row whose syntax was checked at build time
    # but whose domain has never been looked up leaves this null.
    validated_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    # Identifies which outbox run claimed this row, so a run only ever sends the
    # rows it won itself (a status of "sending" alone can belong to another run).
    claim_token = models.UUIDField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("campaign", "email")
        indexes = [models.Index(fields=["campaign", "status"])]

    def __str__(self):
        return f"{self.email} [{self.status}]"


class CampaignExclusion(models.Model):
    """Durable record that an address was deliberately removed from a campaign.

    Removing a draft recipient deletes its `CampaignRecipient` row outright,
    and removing one from an in-flight campaign only marks the row
    `skipped` -- neither leaves any trace that the removal was intentional.
    `build_recipients` re-resolves the audience from its sources on every
    call, so without this the removed address would simply be recreated by
    the next rebuild. This row has to outlive the recipient row it excludes,
    so `build_recipients` can filter the address back out even after the
    original row is gone.
    """

    campaign = models.ForeignKey(
        Campaign, related_name="exclusions", on_delete=models.CASCADE
    )
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("campaign", "email")

    def __str__(self):
        return f"{self.email} excluded from campaign {self.campaign_id}"


class MailThread(models.Model):
    """One conversation in one mailbox.

    A mailbox is the local part of a work address: a staff handle (owner set)
    or a shared name like "info" (owner null). Mail to two staff lands as two
    threads, so each keeps its own read and archived state, as real mail does.
    """

    mailbox = models.CharField(max_length=64, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="mail_threads",
    )
    subject = models.CharField(max_length=500, blank=True, default="")
    # The outside party, for the thread list.
    counterpart_name = models.CharField(max_length=200, blank=True, default="")
    counterpart_email = models.EmailField(blank=True, default="")
    snippet = models.CharField(max_length=200, blank=True, default="")
    unread = models.BooleanField(default=True)
    archived = models.BooleanField(default=False)
    last_message_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-last_message_at"]

    def __str__(self):
        return f"{self.mailbox}: {self.subject[:50]}"


class MailMessage(models.Model):
    DIRECTION_CHOICES = [("in", "Received"), ("out", "Sent")]
    STATUS_CHOICES = [
        ("received", "Received"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    thread = models.ForeignKey(MailThread, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    from_name = models.CharField(max_length=200, blank=True, default="")
    from_email = models.EmailField()
    to = models.JSONField(default=list, blank=True)
    cc = models.JSONField(default=list, blank=True)
    # The work address this copy was delivered to (Bcc included), which is
    # how mail to an unclaimed address finds its owner once it is claimed.
    delivered_to = models.CharField(max_length=254, blank=True, default="", db_index=True)
    subject = models.CharField(max_length=500, blank=True, default="")
    body_text = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="")
    # RFC 5322 Message-ID without angle brackets; what replies thread on.
    message_id = models.CharField(max_length=500, blank=True, default="", db_index=True)
    in_reply_to = models.CharField(max_length=500, blank=True, default="")
    references = models.TextField(blank=True, default="")
    attachments = models.JSONField(default=list, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_mail",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.direction} {self.from_email}: {self.subject[:50]}"
