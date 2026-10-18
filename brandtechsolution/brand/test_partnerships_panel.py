import shutil
import tempfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from brand.models import Career, PartnerOrganisation, PartnershipType
from brand.test_admin_access import staff_user
from staff.tests.helpers import onboarded

LIST = "/admin-panel/partnerships/"

TRACK = {
    "title": "Academic Partner",
    "tagline": "Bring students into real projects.",
    "description": "We co-design coursework with universities.",
    "benefits": "Mentorship\nCloud credits",
    "requirements": "Accredited institution",
    "status": "open",
    "icon": "fas fa-university",
    "accent": "blue",
    "order": "1",
}


class PartnershipsPanelAccessTests(TestCase):
    def test_manage_staff_holder_opens_every_tab(self):
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))
        for tab in ("tracks", "partners", "jobs"):
            response = self.client.get(LIST, {"tab": tab})
            self.assertEqual(response.status_code, 200, tab)

    def test_staff_without_manage_staff_get_403(self):
        self.client.force_login(onboarded(staff_user("writer", "manage_blog")))
        self.assertEqual(self.client.get(LIST).status_code, 403)
        self.assertEqual(self.client.get(f"{LIST}tracks/new/").status_code, 403)

    def test_anonymous_visitors_are_sent_to_login(self):
        response = self.client.get(LIST)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))

    def test_unknown_section_is_404(self):
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))
        self.assertEqual(self.client.get(f"{LIST}widgets/new/").status_code, 404)

    def test_unknown_tab_falls_back_to_tracks(self):
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))
        response = self.client.get(LIST, {"tab": "nope"})
        self.assertEqual(response.context["kind"], "tracks")

    def test_sidebar_links_to_the_panel_page_not_django_admin(self):
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))
        response = self.client.get(LIST)
        self.assertContains(response, 'href="/admin-panel/partnerships/" id="nav-partnerships"')
        self.assertNotContains(response, "/admin/brand/partnershiptype/")


class PartnershipsPanelEditingTests(TestCase):
    def setUp(self):
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))

    def test_add_track_then_listed(self):
        response = self.client.post(f"{LIST}tracks/new/", TRACK)
        self.assertRedirects(response, f"{LIST}?tab=tracks", fetch_redirect_response=False)
        track = PartnershipType.objects.get()
        self.assertEqual(track.benefits_list(), ["Mentorship", "Cloud credits"])
        listing = self.client.get(LIST, {"tab": "tracks"})
        self.assertContains(listing, "Academic Partner")
        self.assertContains(listing, "2 benefits, 1 requirement")

    def test_edit_track(self):
        track = PartnershipType.objects.create(**{**TRACK, "order": 1})
        response = self.client.post(f"{LIST}tracks/{track.pk}/", {**TRACK, "status": "closed"})
        self.assertEqual(response.status_code, 302)
        track.refresh_from_db()
        self.assertEqual(track.status, "closed")

    def test_track_rejects_bad_icon_and_accent(self):
        response = self.client.post(
            f"{LIST}tracks/new/",
            {**TRACK, "icon": "fas fa-x\" onload=\"alert(1)", "accent": "red"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("icon", response.context["form"].errors)
        self.assertIn("accent", response.context["form"].errors)
        self.assertFalse(PartnershipType.objects.exists())

    def test_add_partner_and_reject_script_links(self):
        data = {"name": "Open Lab", "website": "https://lab.example", "featured": "on", "order": "0"}
        self.assertEqual(self.client.post(f"{LIST}partners/new/", data).status_code, 302)
        self.assertTrue(PartnerOrganisation.objects.get().featured)

        response = self.client.post(
            f"{LIST}partners/new/", {**data, "name": "Bad", "logo_url": "javascript:alert(1)"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("logo_url", response.context["form"].errors)

    def test_add_job_and_reject_wrong_document_type(self):
        data = {
            "title": "Field Sales Lead",
            "employment_type": "Full-time",
            "location": "Nairobi",
            "email": f"careers@{settings.MAILBOX_DOMAIN}",
            "status": "open",
            "description": "Grow our school partnerships.",
        }
        bad = SimpleUploadedFile("run.exe", b"MZ", content_type="application/octet-stream")
        response = self.client.post(f"{LIST}jobs/new/", {**data, "document": bad})
        self.assertIn("document", response.context["form"].errors)
        self.assertFalse(Career.objects.exists())

        self.assertEqual(self.client.post(f"{LIST}jobs/new/", data).status_code, 302)
        self.assertContains(self.client.get(LIST, {"tab": "jobs"}), "Field Sales Lead")

    def test_delete_is_post_only(self):
        job = Career.objects.create(title="Intern", description="x")
        url = f"{LIST}jobs/{job.pk}/delete/"
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(Career.objects.filter(pk=job.pk).exists())
        response = self.client.post(url)
        self.assertRedirects(response, f"{LIST}?tab=jobs", fetch_redirect_response=False)
        self.assertFalse(Career.objects.filter(pk=job.pk).exists())

    def test_delete_refused_without_manage_staff(self):
        job = Career.objects.create(title="Intern", description="x")
        self.client.force_login(onboarded(staff_user("writer", "manage_blog")))
        self.assertEqual(self.client.post(f"{LIST}jobs/{job.pk}/delete/").status_code, 403)
        self.assertTrue(Career.objects.filter(pk=job.pk).exists())


class PartnershipsPanelUploadTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))

    def test_job_document_upload_is_saved(self):
        with override_settings(MEDIA_ROOT=self.media):
            pdf = SimpleUploadedFile("role.pdf", b"%PDF-1.4 test", content_type="application/pdf")
            response = self.client.post(f"{LIST}jobs/new/", {
                "title": "Designer", "employment_type": "Contract", "location": "Remote",
                "email": f"careers@{settings.MAILBOX_DOMAIN}", "status": "open", "description": "Design things.", "document": pdf,
            })
            self.assertEqual(response.status_code, 302)
            self.assertTrue(Career.objects.get().document.name.startswith("career_docs/role"))


class PublicTrackCardTests(TestCase):
    def test_card_uses_the_icon_and_colour_chosen_in_the_panel(self):
        PartnershipType.objects.create(**{**TRACK, "icon": "fas fa-microchip", "accent": "emerald"})
        response = self.client.get("/partnerships/")
        self.assertContains(response, '<i class="fas fa-microchip" aria-hidden="true"></i>')
        self.assertContains(response, "text-emerald-500 mb-4")


class PartnershipStatusToggleTests(TestCase):
    """Close / Reopen on tracks and Hide / Show on partners, from the list."""

    def setUp(self):
        self.client.force_login(onboarded(staff_user("boss", "manage_staff")))

    def test_closing_a_track_moves_it_to_the_archived_list(self):
        track = PartnershipType.objects.create(**{**TRACK, "order": 1})
        url = f"{LIST}tracks/{track.pk}/status/"
        response = self.client.post(url)
        self.assertRedirects(response, f"{LIST}?tab=tracks", fetch_redirect_response=False)
        track.refresh_from_db()
        self.assertEqual(track.status, PartnershipType.STATUS_CLOSED)
        page = self.client.get("/partnerships/")
        self.assertIn(track, page.context["closed_types"])
        self.assertNotIn(track, page.context["open_types"])
        self.assertContains(self.client.get(LIST, {"tab": "tracks"}), "Reopen")

        self.client.post(url)
        track.refresh_from_db()
        self.assertEqual(track.status, PartnershipType.STATUS_OPEN)

    def test_hiding_a_partner_takes_it_off_the_partnerships_page(self):
        partner = PartnerOrganisation.objects.create(name="Acme Schools")
        url = f"{LIST}partners/{partner.pk}/status/"
        self.client.post(url)
        partner.refresh_from_db()
        self.assertFalse(partner.featured)
        self.assertNotIn(partner, self.client.get("/partnerships/").context["featured_partners"])
        self.assertContains(self.client.get(LIST, {"tab": "partners"}), "Show")

        self.client.post(url)
        partner.refresh_from_db()
        self.assertTrue(partner.featured)

    def test_toggle_is_post_only_and_refused_without_manage_staff(self):
        track = PartnershipType.objects.create(**{**TRACK, "order": 1})
        url = f"{LIST}tracks/{track.pk}/status/"
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(onboarded(staff_user("writer", "manage_blog")))
        self.assertEqual(self.client.post(url).status_code, 403)
        track.refresh_from_db()
        self.assertEqual(track.status, PartnershipType.STATUS_OPEN)

    def test_tracks_and_partners_can_be_deleted(self):
        track = PartnershipType.objects.create(**{**TRACK, "order": 1})
        partner = PartnerOrganisation.objects.create(name="Acme Schools")
        self.client.post(f"{LIST}tracks/{track.pk}/delete/")
        self.client.post(f"{LIST}partners/{partner.pk}/delete/")
        self.assertFalse(PartnershipType.objects.exists())
        self.assertFalse(PartnerOrganisation.objects.exists())
