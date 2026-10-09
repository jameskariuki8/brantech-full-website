from django.test import SimpleTestCase
from django.template import loader

from .forms import SiteContentForm
from .models import SiteContent


class SiteContentFormTests(SimpleTestCase):
    def make_form_data(self):
        form = SiteContentForm(instance=SiteContent())
        return {name: form[name].value() for name in form.fields}

    def test_accepts_custom_links_and_story_tabs(self):
        data = self.make_form_data()
        data["header_links_text"] = (
            "Home | /\nProducts | /products/\n  EduShare Africa | /products/#edushare"
        )
        data["footer_legal_links_text"] = "Privacy | /privacy/"
        data["story_tabs_text"] = (
            "Our story | A new heading | Page copy | A quote | Team | FEATURED | "
            "/media/story.jpg"
        )

        form = SiteContentForm(data=data, instance=SiteContent())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["header_links_text"],
            [
                {"label": "Home", "url": "/"},
                {
                    "label": "Products",
                    "url": "/products/",
                    "children": [
                        {"label": "EduShare Africa", "url": "/products/#edushare"},
                    ],
                },
            ],
        )
        self.assertEqual(form.cleaned_data["story_tabs_text"][0]["title"], "A new heading")

    def test_rejects_script_urls(self):
        data = self.make_form_data()
        data["header_links_text"] = "Unsafe | javascript:alert(1)"

        form = SiteContentForm(data=data, instance=SiteContent())

        self.assertFalse(form.is_valid())
        self.assertIn("header_links_text", form.errors)

    def test_preserves_spaces_around_hero_title_highlight(self):
        data = self.make_form_data()
        data["hero_title_before"] = "Build something "
        data["hero_title_after"] = " for everyone"

        form = SiteContentForm(data=data, instance=SiteContent())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["hero_title_before"], "Build something ")
        self.assertEqual(form.cleaned_data["hero_title_after"], " for everyone")

    def test_parses_and_saves_custom_landing_cards_and_metrics(self):
        data = self.make_form_data()
        data["capability_cards_text"] = (
            "API SYSTEMS | Custom APIs | Reliable integrations | /media/apis.png | "
            "fas fa-code | Python~fab fa-python; Django~fas fa-server\n"
            + "\n".join(data["capability_cards_text"].splitlines()[1:])
        )
        data["journey_steps_text"] = (
            data["journey_steps_text"].replace(
                "#00FF94 | /static/brand/images/cap_digital_trans.png",
                "#123ABC | /static/brand/images/cap_digital_trans.png",
                1,
            )
        )
        data["impact_stats_text"] = (
            "11 | Projects launched\n"
            + "\n".join(data["impact_stats_text"].splitlines()[1:])
        )

        form = SiteContentForm(data=data, instance=SiteContent())

        self.assertTrue(form.is_valid(), form.errors)
        content = form.save(commit=False)
        self.assertEqual(content.capability_cards[0]["title"], "Custom APIs")
        self.assertEqual(
            content.capability_cards[0]["technologies"],
            [
                {"label": "Python", "icon": "fab fa-python"},
                {"label": "Django", "icon": "fas fa-server"},
            ],
        )
        self.assertEqual(content.journey_steps[0]["color"], "#123ABC")
        self.assertEqual(content.impact_stats[0], {
            "key": "metricProjects",
            "value": 11,
            "label": "Projects launched",
        })

    def test_rejects_unsafe_card_image_urls(self):
        data = self.make_form_data()
        first_card = data["capability_cards_text"].splitlines()
        first_card[0] = first_card[0].replace(
            "/static/brand/images/cap_software_dev.png",
            "javascript:alert(1)",
        )
        data["capability_cards_text"] = "\n".join(first_card)

        form = SiteContentForm(data=data, instance=SiteContent())

        self.assertFalse(form.is_valid())
        self.assertIn("capability_cards_text", form.errors)

    def test_landing_page_renders_editable_content_with_upstream_layout(self):
        content = SiteContent()
        content.brand_name = "Example Studio"
        content.header_cta_label = "Plan a project"
        content.header_links = [
            {
                "label": "Work",
                "url": "/projects/",
                "children": [{"label": "Featured", "url": "/projects/#featured"}],
            },
        ]
        content.hero_title_before = "Build "
        content.hero_title_highlight = "better"
        content.hero_title_after = " systems"
        content.story_tabs = [
            {
                "label": "Our approach",
                "title": "Designed for people",
                "desc": "A customer-first approach.",
                "quote": "Make it useful.",
                "author": "Example Studio",
                "badgeText": "OUR APPROACH",
                "image": "/static/brand/images/story.jpg",
            },
        ]

        html = loader.get_template("brand/index.html").render(
            {"site_content": content}
        )

        self.assertIn("Example Studio", html)
        self.assertIn("Plan a project", html)
        self.assertIn("Featured", html)
        self.assertIn("Build ", html)
        self.assertIn("Designed for people", html)
