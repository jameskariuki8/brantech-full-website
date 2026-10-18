from django.test import TestCase, override_settings

from brand.models import Career
from brand.test_admin_access import staff_user
from staff.tests.helpers import onboarded


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class CareerModelTests(TestCase):
    def test_new_roles_are_open_and_apply_to_our_own_domain(self):
        role = Career.objects.create(title="Intern", description="x")
        self.assertTrue(role.is_open)
        self.assertEqual(role.email, "careers@teklora.co.ke")
        self.assertIsNone(role.closed_at)

    def test_closing_stamps_closed_at_and_reopening_clears_it(self):
        role = Career.objects.create(title="Intern", description="x")
        role.status = Career.STATUS_CLOSED
        role.save()
        self.assertIsNotNone(role.closed_at)
        role.status = Career.STATUS_OPEN
        role.save()
        self.assertIsNone(role.closed_at)

    def test_closed_role_is_found_by_reference(self):
        role = Career.objects.create(title="Designer", description="x", status=Career.STATUS_CLOSED)
        found = Career.closed_role_for(f"Re: application for Designer ({role.reference})", ["careers@teklora.co.ke"])
        self.assertEqual(found, role)

    def test_reference_wins_over_title(self):
        # Two roles share an inbox and a title; the reference picks the open one.
        Career.objects.create(title="Designer", description="x", status=Career.STATUS_CLOSED)
        open_role = Career.objects.create(title="Designer", description="x")
        self.assertIsNone(
            Career.closed_role_for(open_role.application_subject, ["careers@teklora.co.ke"])
        )

    def test_closed_role_is_found_by_title_without_a_reference(self):
        role = Career.objects.create(title="Designer", description="x", status=Career.STATUS_CLOSED)
        self.assertEqual(Career.closed_role_for("Application for Designer", ["careers@teklora.co.ke"]), role)
        self.assertIsNone(Career.closed_role_for("My CV", ["careers@teklora.co.ke"]))

    def test_mail_to_another_address_does_not_match(self):
        role = Career.objects.create(title="Designer", description="x", status=Career.STATUS_CLOSED)
        self.assertIsNone(Career.closed_role_for(role.application_subject, ["info@teklora.co.ke"]))

    def test_open_role_does_not_match(self):
        role = Career.objects.create(title="Designer", description="x")
        self.assertIsNone(Career.closed_role_for(role.application_subject, [role.email]))


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class CareerEmailDomainTests(TestCase):
    URL = "/admin-panel/partnerships/jobs/new/"
    DATA = {
        "title": "Designer", "employment_type": "Contract", "location": "Remote",
        "status": "open", "description": "Design things.",
    }

    def setUp(self):
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))

    def test_address_on_another_domain_is_rejected(self):
        for address in ("careers@teklora.com", "jobs@gmail.com", "careers@teklora.co.ke.evil.com"):
            response = self.client.post(self.URL, {**self.DATA, "email": address})
            self.assertEqual(response.status_code, 200, address)
            self.assertIn("@teklora.co.ke", response.context["form"].errors["email"][0])
        self.assertFalse(Career.objects.exists())

    def test_any_address_on_our_domain_is_accepted(self):
        for address in ("careers@teklora.co.ke", "Jobs@Teklora.co.ke"):
            response = self.client.post(self.URL, {**self.DATA, "email": address})
            self.assertEqual(response.status_code, 302, address)
        self.assertEqual(Career.objects.count(), 2)

    def test_editing_cannot_switch_to_another_domain(self):
        role = Career.objects.create(title="Designer", description="x")
        response = self.client.post(
            f"/admin-panel/partnerships/jobs/{role.pk}/", {**self.DATA, "email": "careers@teklora.com"}
        )
        self.assertEqual(response.status_code, 200)
        role.refresh_from_db()
        self.assertEqual(role.email, "careers@teklora.co.ke")


class CareersPageTests(TestCase):
    def test_closed_roles_leave_the_careers_page(self):
        Career.objects.create(title="Open Role", description="x")
        Career.objects.create(title="Closed Role", description="x", status=Career.STATUS_CLOSED)
        response = self.client.get("/careers/")
        self.assertContains(response, "Open Role")
        self.assertNotContains(response, "Closed Role")

    def test_apply_link_carries_the_reference(self):
        role = Career.objects.create(title="Designer", description="x")
        response = self.client.get("/careers/")
        self.assertContains(response, f"subject=Application%20for%20Designer%20%28JOB-{role.pk}%29")

    def test_empty_state_when_nothing_is_open(self):
        Career.objects.create(title="Closed Role", description="x", status=Career.STATUS_CLOSED)
        self.assertContains(self.client.get("/careers/"), "No open roles right now")


class CareerStatusToggleTests(TestCase):
    def setUp(self):
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))
        self.role = Career.objects.create(title="Intern", description="x")
        self.url = f"/admin-panel/partnerships/jobs/{self.role.pk}/status/"

    def test_close_then_reopen(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, "/admin-panel/partnerships/?tab=jobs", fetch_redirect_response=False)
        self.role.refresh_from_db()
        self.assertFalse(self.role.is_open)
        self.client.post(self.url)
        self.role.refresh_from_db()
        self.assertTrue(self.role.is_open)

    def test_panel_shows_close_and_reopen(self):
        self.assertContains(self.client.get("/admin-panel/partnerships/", {"tab": "jobs"}), "Close")
        self.client.post(self.url)
        self.assertContains(self.client.get("/admin-panel/partnerships/", {"tab": "jobs"}), "Reopen")

    def test_toggle_is_post_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_toggle_refused_without_manage_staff(self):
        self.client.force_login(onboarded(staff_user("writer", "manage_blog")))
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.role.refresh_from_db()
        self.assertTrue(self.role.is_open)
