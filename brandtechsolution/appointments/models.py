from django.utils.translation import gettext_lazy as _
from django.db import models
from datetime import timedelta, datetime

class Appointment(models.Model):

    APPOINTMENT_STATUS_CHOICES = [
        ("pending", _("Pending")),
        ("confirmed", _("Confirmed")),
        ("completed", _("Completed")),
        ("cancelled", _("Cancelled")),
        ("rescheduled", _("Rescheduled"))
    ]

    email = models.EmailField(_("Email"), unique=True, max_length=255)
    phone = models.CharField(_("Phone"), unique=True, max_length=20)
    full_name = models.CharField(_("Full name"), max_length=255)

    title = models.CharField(_("Subject"), max_length=200)
    description = models.TextField(_("Description"))
    date = models.DateField(_("Date"))
    time = models.TimeField(_("Time"))
    estimated_duration = models.IntegerField(_("Estimated duration(Minutes)"))
    status = models.CharField(_("Status"), max_length=20, choices=APPOINTMENT_STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    def __str__(self):
        return self.title

    def calculate_end_time(self):
        start_datetime = datetime.combine(self.date, self.time)
        end_datetime = start_datetime + timedelta(minutes=self.estimated_duration)
        return end_datetime.time()