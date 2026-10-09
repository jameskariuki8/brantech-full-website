from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from staff.models import StaffProfile
from staff.phone import normalize_phone


class NormalizePhoneTest(SimpleTestCase):
    def test_kenyan_local_number_gets_country_code(self):
        self.assertEqual(normalize_phone("0712 345 678"), "+254712345678")

    def test_international_forms_are_accepted(self):
        self.assertEqual(normalize_phone("+254-712-345-678"), "+254712345678")
        self.assertEqual(normalize_phone("00447911123456"), "+447911123456")
        self.assertEqual(normalize_phone("254712345678"), "+254712345678")

    def test_blank_clears_it(self):
        self.assertEqual(normalize_phone("  "), "")

    def test_garbage_is_rejected(self):
        for raw in ("12", "+0712345678", "call me", "+2547123456789012"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                normalize_phone(raw)


class MeApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "ann@example.com", email="ann@example.com", password="old-pass-123",
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_any_staff_member_can_read_their_own_profile(self):
        resp = self.client.get("/api/staff/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], "ann@example.com")
        self.assertEqual(resp.json()["phone"], "")

    def test_non_staff_are_refused(self):
        self.client.force_login(User.objects.create_user("public", password="p"))
        self.assertEqual(self.client.get("/api/staff/me/").status_code, 403)

    def test_update_name_and_phone(self):
        resp = self.client.patch(
            "/api/staff/me/",
            {"first_name": "Ann", "last_name": "Wanjiru", "phone": "0712 345 678"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["phone"], "+254712345678")
        self.user.refresh_from_db()
        self.assertEqual(self.user.get_full_name(), "Ann Wanjiru")
        self.assertEqual(StaffProfile.objects.get(user=self.user).phone, "+254712345678")

    def test_invalid_phone_is_a_field_error(self):
        resp = self.client.patch(
            "/api/staff/me/", {"phone": "call me"}, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("phone", resp.json())

    def test_email_and_username_cannot_be_changed_here(self):
        self.client.patch(
            "/api/staff/me/",
            {"email": "evil@example.com", "username": "root"},
            content_type="application/json",
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ann@example.com")
        self.assertEqual(self.user.username, "ann@example.com")

    def test_update_coding_capabilities_and_profile(self):
        resp = self.client.patch(
            "/api/staff/me/",
            {
                "primary_role": "AI Engineer",
                "coding_languages": ["Python", "C++"],
                "frameworks": ["Django", "PyTorch"],
                "github_username": "annai",
                "bio": "Building autonomous systems",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["primary_role"], "AI Engineer")
        self.assertEqual(data["coding_languages"], ["Python", "C++"])
        self.assertEqual(data["frameworks"], ["Django", "PyTorch"])
        self.assertEqual(data["github_username"], "annai")
        self.assertEqual(data["bio"], "Building autonomous systems")

    def test_people_list_shows_capabilities_and_phone(self):
        StaffProfile.objects.create(
            user=self.user,
            phone="+254712345678",
            primary_role="Fullstack Engineer",
            coding_languages=["Python", "TypeScript"],
            frameworks=["Django", "React"],
            github_username="anncode",
            is_onboarded=True,
        )
        self.user.is_superuser = True
        self.user.save()
        people = self.client.get("/api/staff/people/").json()["results"]
        self.assertEqual(people[0]["phone"], "+254712345678")
        self.assertEqual(people[0]["primary_role"], "Fullstack Engineer")
        self.assertEqual(people[0]["coding_languages"], ["Python", "TypeScript"])
        self.assertTrue(people[0]["is_onboarded"])


class ChangePasswordTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "ann", password="old-pass-123", is_staff=True
        )
        self.client.force_login(self.user)

    def post(self, current, new):
        return self.client.post(
            "/api/staff/me/password/",
            {"current_password": current, "new_password": new},
            content_type="application/json",
        )

    def test_changes_password_and_keeps_the_session(self):
        self.assertEqual(self.post("old-pass-123", "a-much-better-one-42").status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("a-much-better-one-42"))
        self.assertEqual(self.client.get("/api/staff/me/").status_code, 200)

    def test_wrong_current_password_is_refused(self):
        resp = self.post("not-it", "a-much-better-one-42")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("current_password", resp.json())
