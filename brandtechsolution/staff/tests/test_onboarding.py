from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from staff.models import AuditEntry, StaffProfile


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class OnboardingFlowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "ann.wanjiru", email="ann@example.com", password="pass-12345-abc",
            is_staff=True,
        )
        self.profile = StaffProfile.objects.create(user=self.user, is_onboarded=False)
        self.client.force_login(self.user)

    def test_non_staff_redirected_to_home(self):
        public_user = User.objects.create_user("public", password="p")
        self.client.force_login(public_user)
        resp = self.client.get("/staff/onboarding/")
        self.assertEqual(resp.status_code, 302)

    def test_user_needing_handle_redirected_to_address_first(self):
        invited_user = User.objects.create_user(
            "dev@example.com", email="dev@example.com", is_staff=True
        )
        StaffProfile.objects.create(user=invited_user, is_onboarded=False)
        self.client.force_login(invited_user)
        resp = self.client.get("/staff/onboarding/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/staff/address/", resp["Location"])

    def test_get_onboarding_renders_form(self):
        resp = self.client.get("/staff/onboarding/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Welcome to the Team!")
        self.assertContains(resp, "WhatsApp Number")
        self.assertContains(resp, "Python")
        self.assertContains(resp, "Django")

    def test_post_missing_phone_shows_error(self):
        resp = self.client.post("/staff/onboarding/", {
            "phone": "",
            "primary_role": "Backend Developer",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "WhatsApp phone number is required")
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_onboarded)

    def test_post_invalid_phone_shows_error(self):
        resp = self.client.post("/staff/onboarding/", {
            "phone": "invalid-phone",
            "primary_role": "Backend Developer",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter a phone number with its country code")
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_onboarded)

    def test_post_valid_onboarding_saves_capabilities_and_whatsapp(self):
        resp = self.client.post("/staff/onboarding/", {
            "phone": "0712 345 678",
            "primary_role": "Fullstack Engineer",
            "coding_languages": ["Python", "TypeScript"],
            "custom_languages": "Rust, Go",
            "frameworks": ["Django", "React"],
            "custom_frameworks": "Docker, Tailwind CSS",
            "github_username": "annwanjiru",
            "bio": "Fullstack builder focusing on AI and Django.",
            "next": "/admin-panel/",
        })
        self.assertRedirects(resp, "/admin-panel/", fetch_redirect_response=False)

        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_onboarded)
        self.assertEqual(self.profile.phone, "+254712345678")
        self.assertEqual(self.profile.primary_role, "Fullstack Engineer")
        self.assertEqual(
            sorted(self.profile.coding_languages),
            ["Go", "Python", "Rust", "TypeScript"]
        )
        self.assertEqual(
            sorted(self.profile.frameworks),
            ["Django", "Docker", "React", "Tailwind CSS"]
        )
        self.assertEqual(self.profile.github_username, "annwanjiru")
        self.assertEqual(self.profile.bio, "Fullstack builder focusing on AI and Django.")

        # Audit entry was written
        audit = AuditEntry.objects.filter(action="onboarding_completed", target_user=self.user).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.detail["phone"], "+254712345678")
        self.assertEqual(audit.detail["primary_role"], "Fullstack Engineer")

    def test_middleware_redirects_unonboarded_user(self):
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/staff/onboarding/?next="))

    def test_middleware_allows_onboarded_user(self):
        self.profile.is_onboarded = True
        self.profile.save()
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 200)
