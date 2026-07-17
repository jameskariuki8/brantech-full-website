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


class EmailTemplate(models.Model):
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=255)
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
