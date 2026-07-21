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

    def test_deactivated_staff_is_denied(self):
        """Mirrors the decorator-side deactivation test: has_capability()
        must deny a deactivated staff account even though is_staff is True
        and the capability was granted. This relies on has_perm() denying
        inactive users (via ModelBackend and the superuser bypass both
        requiring is_active). If has_capability() were ever changed to
        check is_staff and a cached/raw permission set without going
        through is_active-aware has_perm(), a deactivated account would
        keep API access."""
        user = grant(
            User.objects.create_user("u", password="p", is_staff=True),
            "send_campaigns",
        )
        user.is_active = False
        user.save()
        user = User.objects.get(pk=user.pk)  # drop the permission cache

        self.assertFalse(self._check(user))


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

    def test_non_staff_with_the_capability_is_denied(self):
        """is_staff is a floor here too: the DRF side already covers this
        case (test_non_staff_with_the_permission_is_denied above), but the
        decorator has its own is_staff check and can regress independently.
        If someone later simplified the decorator to check only
        has_perm(), a non-staff user who signed up through the public
        /signup/ page and was (incorrectly) granted a capability would be
        able to reach panel views."""
        from django.core.exceptions import PermissionDenied

        request = self.factory.get("/appointments/")
        request.user = grant(
            User.objects.create_user("u", password="p"), "manage_appointments"
        )
        with self.assertRaises(PermissionDenied):
            self.view(request)

    def test_deactivated_staff_is_denied(self):
        """Deactivating a staff account must revoke panel access even
        though is_staff and the capability grant are still in place. This
        currently works only as a side effect of Django internals:
        ModelBackend.get_all_permissions() returns empty for an inactive
        user and PermissionsMixin.has_perm()'s superuser bypass requires
        is_active. If that reliance were ever removed or replaced with a
        naive is_staff-and-has_perm check that ignores is_active, a
        deactivated staff account would silently regain access."""
        from django.core.exceptions import PermissionDenied

        user = grant(
            User.objects.create_user("u", password="p", is_staff=True),
            "manage_appointments",
        )
        user.is_active = False
        user.save()
        user = User.objects.get(pk=user.pk)  # drop the permission cache

        request = self.factory.get("/appointments/")
        request.user = user
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
