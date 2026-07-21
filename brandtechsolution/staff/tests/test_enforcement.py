from django.contrib.auth.models import Permission, User
from django.test import RequestFactory, TestCase
from rest_framework.test import APIRequestFactory

from staff.decorators import capability_required
from staff.permissions import has_capability


def grant(user, codename):
    user.user_permissions.add(
        Permission.objects.get(
            codename=codename, content_type__app_label="staff"
        )
    )
    return User.objects.get(pk=user.pk)  # drop the permission cache


class HasCapabilityTest(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = has_capability("send_campaigns")()

    def _check(self, user):
        request = self.factory.get("/")
        request.user = user
        return self.permission.has_permission(request, None)

    def test_anonymous_is_denied(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(self._check(AnonymousUser()))

    def test_non_staff_with_the_permission_is_denied(self):
        """is_staff is a floor: the panel is not for ordinary accounts."""
        user = grant(User.objects.create_user("u", password="p"), "send_campaigns")
        self.assertFalse(self._check(user))

    def test_staff_without_the_capability_is_denied(self):
        user = User.objects.create_user("u", password="p", is_staff=True)
        self.assertFalse(self._check(user))

    def test_staff_with_the_capability_is_allowed(self):
        user = grant(
            User.objects.create_user("u", password="p", is_staff=True),
            "send_campaigns",
        )
        self.assertTrue(self._check(user))

    def test_staff_with_a_different_capability_is_denied(self):
        user = grant(
            User.objects.create_user("u", password="p", is_staff=True),
            "manage_blog",
        )
        self.assertFalse(self._check(user))

    def test_superuser_is_allowed(self):
        self.assertTrue(self._check(User.objects.create_superuser("r", password="p")))


class CapabilityRequiredTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        @capability_required("manage_appointments")
        def view(request):
            from django.http import HttpResponse

            return HttpResponse("ok")

        self.view = view

    def test_anonymous_is_redirected_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/appointments/")
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_staff_without_the_capability_gets_403(self):
        from django.core.exceptions import PermissionDenied

        request = self.factory.get("/appointments/")
        request.user = User.objects.create_user("u", password="p", is_staff=True)
        with self.assertRaises(PermissionDenied):
            self.view(request)

    def test_staff_with_the_capability_passes(self):
        request = self.factory.get("/appointments/")
        request.user = grant(
            User.objects.create_user("u", password="p", is_staff=True),
            "manage_appointments",
        )
        self.assertEqual(self.view(request).status_code, 200)

    def test_superuser_passes(self):
        request = self.factory.get("/appointments/")
        request.user = User.objects.create_superuser("r", password="p")
        self.assertEqual(self.view(request).status_code, 200)
