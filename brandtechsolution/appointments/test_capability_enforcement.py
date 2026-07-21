from django.contrib.auth.models import Permission, User
from django.test import TestCase

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
