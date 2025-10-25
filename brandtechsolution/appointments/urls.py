from django.urls import path

from appointments.views import (
    AppointmentsListView,
    create_appointment,
    get_appointment,
    check_availability,
    admin_manage_appointment,
)

app_name = 'appointments'

urlpatterns = [
    path('', AppointmentsListView.as_view(), name='list'),
    path('create/', create_appointment, name='create'),
    path('get/', get_appointment, name='get'),
    path('check-availability/', check_availability, name='check_availability'),
    path('admin/manage/<int:appointment_id>/', admin_manage_appointment, name='admin_manage'),
]