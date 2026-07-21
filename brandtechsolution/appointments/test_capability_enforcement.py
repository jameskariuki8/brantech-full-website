from datetime import date, time, timedelta

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from appointments.models import Appointment


def staff_with(*codenames):
    user = User.objects.create_user("cap", password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


def non_staff_with(*codenames):
    user = User.objects.create_user("noncap", password="p")
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)  # drop the permission cache


class AppointmentsListCapabilityTest(TestCase):
    def test_staff_without_capability_is_denied(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/appointments/").status_code, 403)

    def test_manage_appointments_is_allowed(self):
        self.client.force_login(staff_with("manage_appointments"))
        self.assertEqual(self.client.get("/appointments/").status_code, 200)

    def test_anonymous_is_redirected(self):
        resp = self.client.get("/appointments/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_superuser_is_allowed(self):
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        self.assertEqual(self.client.get("/appointments/").status_code, 200)

    def test_non_staff_with_the_capability_is_denied(self):
        """is_staff is a floor here too: AppointmentsListView.test_func used
        to check only has_perm("staff.manage_appointments"), and has_perm()
        never consults is_staff on its own (ModelBackend.has_perm only cares
        about is_active; PermissionsMixin.has_perm only special-cases active
        superusers). A non-staff account that was granted the
        manage_appointments permission directly through the unmodified
        default /admin/ UserAdmin -- including one that originally signed up
        through the public /signup/ page -- would then reach the staff
        appointments list despite never having been made staff. This guards
        against that regression by asserting such a user is denied."""
        self.client.force_login(non_staff_with("manage_appointments"))
        self.assertEqual(self.client.get("/appointments/").status_code, 403)


class AdminManageAppointmentAnonymousTest(TestCase):
    """End-to-end coverage for capability_required's redirect behaviour on
    admin_manage_appointment's real URL. The decorator's anonymous-redirect
    path was previously exercised only against a synthetic view built in
    staff/tests/test_enforcement.py's CapabilityRequiredTest, never through
    this view's actual URL, urlconf, and middleware stack. This proves an
    anonymous request hitting the real appointments:admin_manage route is
    bounced to /login/ (302) rather than surfacing a bare PermissionDenied
    (403), which would happen if the view's URL wiring or middleware ever
    stopped presenting the request as anonymous before the decorator runs."""

    def test_anonymous_request_is_redirected_to_login(self):
        appointment = Appointment.objects.create(
            email="anon-guard@example.com",
            phone="5550001111",
            full_name="Anon Guard",
            title="Anon Guard Appointment",
            description="Guards the anonymous redirect path.",
            date=date.today() + timedelta(days=1),
            time=time(9, 0),
            estimated_duration=30,
            status="pending",
        )

        resp = self.client.get(
            reverse("appointments:admin_manage", kwargs={"appointment_id": appointment.id})
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])
