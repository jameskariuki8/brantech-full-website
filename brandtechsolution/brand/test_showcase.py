"""The /products/ showcase, now that its content lives in the database.

The page used to hold its own content as markup. These tests pin the things
that move would quietly break: that the six products survived the migration,
that the page still renders each one's theming, and that the panel API can
read and write the showcase half without a manage_projects holder's edit
leaking to someone who does not hold it.
"""
import json

from django.contrib.auth.models import Permission, User
from django.test import TestCase

from brand.models import Project, ProjectFeature, ProjectImage, ProjectNote


SEEDED_SLUGS = [
    "edushare", "dommaterdei", "poise", "kiamiko", "campus-food", "holodesk",
]


class ShowcaseDataMigrationTests(TestCase):
    """The six products the migration carried over."""

    def test_all_six_products_are_present_and_flagged(self):
        slugs = set(Project.objects.filter(showcase=True).values_list("slug", flat=True))
        self.assertEqual(slugs, set(SEEDED_SLUGS))

    def test_products_are_spread_across_the_three_phases(self):
        counts = {}
        for phase, _label in Project.PHASE_CHOICES:
            counts[phase] = Project.objects.filter(showcase=True, phase=phase).count()
        self.assertEqual(counts, {"completed": 3, "active": 2, "future": 1})

    def test_every_product_kept_its_gallery_and_chart(self):
        for slug in SEEDED_SLUGS:
            with self.subTest(slug=slug):
                project = Project.objects.get(slug=slug)
                self.assertEqual(project.gallery.count(), 2)
                self.assertIn("type", project.chart_spec)
                self.assertTrue(project.badge_label)
                self.assertTrue(project.accent.startswith("#"))

    def test_the_two_shade_accent_survives(self):
        """Poise drew its text and its badge fill from different shades."""
        poise = Project.objects.get(slug="poise")
        self.assertEqual(poise.accent, "#C084FC")
        self.assertEqual(poise.fill, "#A855F7")

    def test_a_single_shade_accent_falls_back_to_itself(self):
        edushare = Project.objects.get(slug="edushare")
        self.assertEqual(edushare.accent_deep, "")
        self.assertEqual(edushare.fill, edushare.accent)

    def test_holodesk_kept_the_structure_the_others_never_had(self):
        holodesk = Project.objects.get(slug="holodesk")
        self.assertEqual(holodesk.card_variant, Project.VARIANT_SPOTLIGHT)
        self.assertEqual([n.heading for n in holodesk.notes.all()],
                         ["The Problem", "The HoloDesk Solution"])
        self.assertEqual(len(holodesk.chip_features), 6)
        self.assertEqual(len(holodesk.check_features), 4)
        self.assertEqual(len(holodesk.card_features), 0)

    def test_the_other_products_have_no_notes_or_chips(self):
        for slug in set(SEEDED_SLUGS) - {"holodesk"}:
            with self.subTest(slug=slug):
                project = Project.objects.get(slug=slug)
                self.assertEqual(project.notes.count(), 0)
                self.assertEqual(len(project.chip_features), 0)
                self.assertTrue(project.card_features)


class ProductsPageTests(TestCase):
    """What a visitor gets."""

    def test_every_product_renders(self):
        html = self.client.get("/products/").content.decode()
        for slug in SEEDED_SLUGS:
            with self.subTest(slug=slug):
                self.assertIn(f'id="{slug}"', html)

    def test_theming_reaches_the_markup(self):
        html = self.client.get("/products/").content.decode()
        # accent and the deeper badge fill, as arbitrary Tailwind values
        self.assertIn("bg-[#A855F7]/10", html)      # poise badge fill
        self.assertIn("text-[#C084FC]", html)        # poise badge text
        self.assertIn("In Active Build &bull; Conversational Commerce".replace("&bull;", "•"), html)
        self.assertIn("fab fa-whatsapp", html)       # brand icon, not fas

    def test_phase_dots_keep_their_animations(self):
        html = self.client.get("/products/").content.decode()
        self.assertIn("bg-[#25D366] animate-ping", html)   # active
        self.assertIn("bg-[#38BDF8] animate-pulse", html)  # future
        self.assertIn('rounded-full bg-[#00FF94]"', html)  # completed, no animation

    def test_filter_tab_counts_come_from_the_data(self):
        html = self.client.get("/products/").content.decode()
        self.assertIn("All Products (6)", html)
        self.assertIn("(3)", html)
        self.assertIn("(2)", html)

        Project.objects.filter(slug="poise").update(showcase=False)
        html = self.client.get("/products/").content.decode()
        self.assertIn("All Products (5)", html)
        self.assertNotIn('id="poise"', html)

    def test_charts_are_emitted_as_inert_json(self):
        response = self.client.get("/products/")
        html = response.content.decode()
        self.assertIn('id="product-charts" type="application/json"', html)
        blob = html.split('id="product-charts" type="application/json">')[1].split("</script>")[0]
        charts = json.loads(blob)
        self.assertEqual(set(charts), set(SEEDED_SLUGS))
        self.assertEqual(charts["holodesk"]["type"], "radar")
        self.assertEqual(charts["edushare"]["type"], "doughnut")

    def test_a_product_without_a_chart_renders_without_a_canvas(self):
        Project.objects.filter(slug="poise").update(chart_spec=None)
        html = self.client.get("/products/").content.decode()
        self.assertIn('id="poise"', html)
        self.assertNotIn('id="chart-poise"', html)

    def test_an_empty_phase_drops_its_whole_band(self):
        Project.objects.filter(phase="future").update(showcase=False)
        html = self.client.get("/products/").content.decode()
        self.assertNotIn('data-phase="future"', html)
        self.assertNotIn("Phase 3", html)

    def test_non_showcase_projects_stay_off_the_page(self):
        Project.objects.create(title="Internal tool", description="x", showcase=False)
        html = self.client.get("/products/").content.decode()
        self.assertNotIn("Internal tool", html)

    def test_the_page_does_not_scale_its_queries_with_the_product_count(self):
        """prefetch_related covers all three child collections."""
        with self.assertNumQueries(4):
            self.client.get("/products/")


class ShowcaseApiReadTests(TestCase):
    def test_the_list_carries_the_showcase_fields(self):
        payload = json.loads(self.client.get("/api/projects/").content)
        holodesk = next(p for p in payload if p["slug"] == "holodesk")
        self.assertTrue(holodesk["showcase"])
        self.assertEqual(holodesk["phase"], "future")
        self.assertEqual(holodesk["card_variant"], "spotlight")
        self.assertEqual(len(holodesk["gallery"]), 2)
        self.assertEqual(len(holodesk["notes"]), 2)
        self.assertEqual(holodesk["chart_spec"]["type"], "radar")

    def test_the_detail_endpoint_carries_them_too(self):
        project = Project.objects.get(slug="edushare")
        payload = json.loads(self.client.get(f"/api/projects/{project.pk}/").content)
        self.assertEqual(payload["badge_label"], "Deployed SaaS Platform")
        self.assertEqual(len(payload["features"]), 3)


class ShowcaseApiWriteTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("editor", password="pw", is_staff=True)
        self.editor.user_permissions.add(Permission.objects.get(codename="manage_projects"))
        self.bystander = User.objects.create_user("bystander", password="pw", is_staff=True)
        self.project = Project.objects.get(slug="edushare")

    def _payload(self, **overrides):
        payload = {
            "title": self.project.title,
            "description": self.project.description,
            "has_showcase_fields": "true",
            "showcase": "true",
            "phase": "active",
            "display_order": "7",
            "accent": "#123456",
            "badge_label": "Rebadged",
        }
        payload.update(overrides)
        return payload

    def test_a_holder_can_edit_the_showcase_fields(self):
        self.client.force_login(self.editor)
        response = self.client.post(f"/api/projects/{self.project.pk}/", self._payload())
        self.assertEqual(response.status_code, 200)

        self.project.refresh_from_db()
        self.assertEqual(self.project.phase, "active")
        self.assertEqual(self.project.display_order, 7)
        self.assertEqual(self.project.accent, "#123456")
        self.assertEqual(self.project.badge_label, "Rebadged")

    def test_a_staff_account_without_the_capability_is_refused(self):
        self.client.force_login(self.bystander)
        response = self.client.post(f"/api/projects/{self.project.pk}/", self._payload())
        self.assertEqual(response.status_code, 403)

        self.project.refresh_from_db()
        self.assertEqual(self.project.phase, "completed")

    def test_an_anonymous_caller_is_refused(self):
        response = self.client.post(f"/api/projects/{self.project.pk}/", self._payload())
        self.assertEqual(response.status_code, 401)

    def test_unticking_showcase_takes_the_product_off_the_page(self):
        self.client.force_login(self.editor)
        # An unticked checkbox posts nothing at all, which is why the form
        # sends has_showcase_fields alongside it.
        payload = self._payload()
        del payload["showcase"]
        self.client.post(f"/api/projects/{self.project.pk}/", payload)

        self.project.refresh_from_db()
        self.assertFalse(self.project.showcase)

    def test_a_ticked_checkbox_reads_as_true(self):
        """A bare HTML checkbox posts "on", not "true".

        Regression: the API compared against "true" only, so saving from the
        panel with the box ticked quietly took the product off /products/.
        """
        self.client.force_login(self.editor)
        for wire_value in ("on", "true", "1"):
            with self.subTest(wire_value=wire_value):
                Project.objects.filter(pk=self.project.pk).update(showcase=False)
                self.client.post(
                    f"/api/projects/{self.project.pk}/",
                    self._payload(showcase=wire_value),
                )
                self.project.refresh_from_db()
                self.assertTrue(self.project.showcase)

    def test_an_explicit_false_still_unsets_it(self):
        self.client.force_login(self.editor)
        self.client.post(f"/api/projects/{self.project.pk}/", self._payload(showcase="false"))
        self.project.refresh_from_db()
        self.assertFalse(self.project.showcase)

    def test_a_caller_that_omits_the_marker_cannot_blank_the_theming(self):
        """The blog form and the GitHub sync post neither field."""
        self.client.force_login(self.editor)
        self.client.post(f"/api/projects/{self.project.pk}/", {
            "title": "Renamed only",
            "description": self.project.description,
        })
        self.project.refresh_from_db()
        self.assertEqual(self.project.title, "Renamed only")
        self.assertTrue(self.project.showcase)
        self.assertEqual(self.project.badge_label, "Deployed SaaS Platform")

    def test_collections_are_replaced_wholesale(self):
        self.client.force_login(self.editor)
        response = self.client.post(f"/api/projects/{self.project.pk}/", self._payload(
            features=json.dumps([
                {"style": "card", "icon": "fas fa-bolt", "label": "One", "text": "First"},
                {"style": "check", "icon": "fas fa-check", "text": "Two"},
            ]),
        ))
        self.assertEqual(response.status_code, 200)

        features = list(self.project.features.all())
        self.assertEqual([f.text for f in features], ["First", "Two"])
        self.assertEqual([f.order for f in features], [0, 1])

    def test_a_collection_the_payload_omits_is_left_alone(self):
        self.client.force_login(self.editor)
        before = self.project.features.count()
        self.client.post(f"/api/projects/{self.project.pk}/", self._payload())
        self.assertEqual(self.project.features.count(), before)

    def test_malformed_chart_json_is_rejected_rather_than_stored(self):
        self.client.force_login(self.editor)
        response = self.client.post(
            f"/api/projects/{self.project.pk}/",
            self._payload(chart_spec="{not json"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("chart_spec", json.loads(response.content)["error"])

        self.project.refresh_from_db()
        self.assertEqual(self.project.chart_spec["type"], "doughnut")

    def test_creating_a_showcase_product_from_the_panel(self):
        self.client.force_login(self.editor)
        response = self.client.post("/api/projects/", {
            "title": "Brand new platform",
            "description": "Long form copy.",
            "short_description": "Short copy.",
            "has_showcase_fields": "true",
            "showcase": "true",
            "phase": "future",
            "accent": "#ABCDEF",
            "badge_label": "Concept",
            "chart_spec": json.dumps({"type": "bar", "data": {"labels": [], "datasets": []}}),
            "gallery": json.dumps([{"remote_url": "https://example.com/a.png", "caption": "A"}]),
        })
        self.assertEqual(response.status_code, 201)

        created = Project.objects.get(pk=json.loads(response.content)["id"])
        self.assertTrue(created.showcase)
        self.assertEqual(created.slug, "brand-new-platform")
        self.assertEqual(created.gallery.count(), 1)
        self.assertEqual(created.chart_spec["type"], "bar")

        html = self.client.get("/products/").content.decode()
        self.assertIn("Brand new platform", html)


class ProjectImageResolutionTests(TestCase):
    def test_a_static_path_resolves_through_the_static_url(self):
        image = ProjectImage.objects.get(project__slug="edushare", order=0)
        self.assertEqual(image.src, "/static/brand/images/edushare.png")

    def test_the_lightbox_falls_back_to_the_tile_when_no_full_url_is_set(self):
        image = ProjectImage.objects.get(project__slug="edushare", order=0)
        self.assertEqual(image.expanded_src, image.src)

    def test_a_remote_pair_keeps_its_larger_render(self):
        image = ProjectImage.objects.get(project__slug="campus-food", order=0)
        self.assertIn("w=800", image.src)
        self.assertIn("w=1200", image.expanded_src)


class ProjectSlugTests(TestCase):
    def test_a_slug_is_derived_when_not_given(self):
        project = Project.objects.create(title="Some New Thing", description="x")
        self.assertEqual(project.slug, "some-new-thing")

    def test_an_explicit_slug_is_kept(self):
        project = Project.objects.create(title="Some New Thing", slug="custom", description="x")
        self.assertEqual(project.slug, "custom")
