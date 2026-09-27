from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from staff.handles import suggest_handles, validate_handle
from staff.models import AuditEntry


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class ValidateHandleTest(TestCase):
    def test_normalises_case_and_whitespace(self):
        self.assertEqual(validate_handle("  David.Njihia "), "david.njihia")

    def test_rejects_bad_shapes(self):
        for raw in ("ab", "x" * 31, ".david", "david.", "da vid", "da_vid",
                    "da..vid", "da.-vid", "davíd", "david@teklora.co.ke"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                validate_handle(raw)

    def test_rejects_reserved_and_shared_names(self):
        for raw in ("admin", "info", "support", "hello", "postmaster", "noreply"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                validate_handle(raw)

    def test_rejects_a_taken_handle_in_any_case(self):
        User.objects.create_user("ann")
        with self.assertRaises(ValidationError):
            validate_handle("ANN")

    def test_suggestions_come_from_the_name_and_skip_taken_ones(self):
        User.objects.create_user("david.njihia")
        user = User(username="d@example.com", email="davidnjihia536@gmail.com",
                    first_name="David", last_name="Njihia")
        suggestions = suggest_handles(user)
        self.assertNotIn("david.njihia", suggestions)
        self.assertIn("davidn", suggestions)
        self.assertIn("davidnjihia", suggestions)


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class ChooseHandleFlowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "ann@example.com", email="ann@example.com", password="pass-12345-abc",
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_panel_pages_redirect_until_a_handle_is_chosen(self):
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/staff/address/?next="))

    def test_apis_are_not_redirected(self):
        self.assertEqual(self.client.get("/api/staff/me/").status_code, 200)

    def test_choosing_a_handle_renames_the_account_once(self):
        resp = self.client.post(
            "/staff/address/", {"handle": "Ann.Wanjiru", "next": "/admin-panel/"}
        )
        self.assertRedirects(resp, "/admin-panel/", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "ann.wanjiru")
        self.assertEqual(self.user.email, "ann@example.com")
        self.assertTrue(AuditEntry.objects.filter(action="handle_chosen").exists())
        self.assertEqual(
            self.client.get("/api/staff/me/").json()["mailbox"], "ann.wanjiru@teklora.co.ke"
        )

        # Picked once: a second submit changes nothing.
        self.client.post("/staff/address/", {"handle": "annw"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "ann.wanjiru")

    def test_invalid_handle_rerenders_with_the_error(self):
        resp = self.client.post("/staff/address/", {"handle": "admin"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "reserved")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "ann@example.com")

    def test_offsite_next_is_ignored(self):
        resp = self.client.post(
            "/staff/address/", {"handle": "annw", "next": "https://evil.example/"}
        )
        self.assertRedirects(resp, "/admin-panel/", fetch_redirect_response=False)

    def test_mailbox_is_null_before_choosing(self):
        self.assertIsNone(self.client.get("/api/staff/me/").json()["mailbox"])


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class LoginWithHandleTest(TestCase):
    def setUp(self):
        User.objects.create_user(
            "ann.wanjiru", email="ann@example.com", password="pass-12345-abc", is_staff=True
        )

    def login(self, identifier):
        return self.client.post(
            "/login/", {"email": identifier, "password": "pass-12345-abc", "next": "/admin-panel/"}
        )

    def test_handle_work_address_and_personal_email_all_sign_in(self):
        for identifier in ("ann.wanjiru", "Ann.Wanjiru", "ann.wanjiru@teklora.co.ke",
                           "ann@example.com"):
            with self.subTest(identifier=identifier):
                self.client.logout()
                resp = self.login(identifier)
                self.assertEqual(resp.status_code, 302, identifier)
                self.assertIn("_auth_user_id", self.client.session)
