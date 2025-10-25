from django.contrib import admin

from appointments.models import Appointment

@admin.register(Appointment)
class AppointmentsAdmin(admin.ModelAdmin):
    list_display = ("title", "description", "date", "time", "estimated_duration", "status")
    list_filter = ("status",)
    search_fields = ("title", "description")
    list_editable = ("status",)
    list_per_page = 10
    list_max_show_all = 100