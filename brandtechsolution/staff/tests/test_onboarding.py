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
            "scopes": ["Engineering", "Product & Design"],
            "custom_scopes": "Training, engineering",
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
        # Custom entries join the ticked ones; a repeat differing only in case is dropped.
        self.assertEqual(
            self.profile.scopes, ["Engineering", "Product & Design", "Training"]
        )
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
        self.assertEqual(audit.detail["scopes"], ["Engineering", "Product & Design", "Training"])

    def test_get_onboarding_offers_business_scopes(self):
        resp = self.client.get("/staff/onboarding/")
        for scope in ("Marketing", "Sales &amp; Partnerships", "Operations", "Finance &amp; Admin"):
            self.assertContains(resp, scope)
        self.assertContains(resp, "Marketing Lead")

    def test_post_without_a_scope_is_refused_and_keeps_the_rest(self):
        resp = self.client.post("/staff/onboarding/", {
            "phone": "0712 345 678",
            "primary_role": "Marketing Lead",
            "bio": "Runs the socials",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Pick at least one area you work in")
        self.assertContains(resp, "0712 345 678")
        self.assertContains(resp, "Runs the socials")
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_onboarded)

    def test_marketing_person_can_onboard_without_any_technical_skills(self):
        resp = self.client.post("/staff/onboarding/", {
            "phone": "0712 345 678",
            "scopes": ["Marketing"],
            "primary_role": "Marketing Lead",
        })
        self.assertEqual(resp.status_code, 302)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_onboarded)
        self.assertEqual(self.profile.scopes, ["Marketing"])
        self.assertEqual(self.profile.coding_languages, [])

    def test_a_failed_post_keeps_the_ticked_scopes(self):
        resp = self.client.post("/staff/onboarding/", {
            "phone": "nope",
            "scopes": ["Marketing"],
        })
        self.assertContains(resp, 'value="Marketing"')
        self.assertContains(resp, "checked")

    def test_middleware_redirects_unonboarded_user(self):
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/staff/onboarding/?next="))

    def test_middleware_allows_onboarded_user(self):
        self.profile.is_onboarded = True
        self.profile.save()
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 200)


class EveryoneOnboardsTest(TestCase):
    """Nobody who works here skips onboarding, whatever row they happen to have."""

    def test_staff_without_a_profile_is_sent_to_onboarding(self):
        # Accounts older than the feature, or made by createsuperuser or
        # /admin/, have no StaffProfile row at all.
        user = User.objects.create_user("old.hand", password="p", is_staff=True)
        self.assertFalse(StaffProfile.objects.filter(user=user).exists())
        self.client.force_login(user)
        for path in ("/admin-panel/", "/appointments/", "/editorial/"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertTrue(resp["Location"].startswith("/staff/onboarding/?next="), path)

    def test_staff_without_a_profile_can_complete_onboarding(self):
        user = User.objects.create_user("old.hand", password="p", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get("/staff/onboarding/").status_code, 200)

        resp = self.client.post(
            "/staff/onboarding/", {"phone": "0712345678", "scopes": ["Operations"]}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(StaffProfile.objects.get(user=user).is_onboarded)
        self.assertEqual(self.client.get("/admin-panel/").status_code, 200)

    def test_superuser_without_staff_flag_is_sent_to_onboarding(self):
        # The panel admits a superuser on either flag, so the gate must too.
        user = User.objects.create_user("owner", password="p", is_superuser=True)
        self.client.force_login(user)
        resp = self.client.get("/admin-panel/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/staff/onboarding/?next="))
        self.assertEqual(self.client.get("/staff/onboarding/").status_code, 200)

    def test_people_without_staff_or_superuser_are_left_alone(self):
        user = User.objects.create_user("public", password="p")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/staff/onboarding/").status_code, 302)
        self.assertNotIn("/staff/onboarding/", self.client.get("/staff/onboarding/")["Location"])
