from importlib import import_module

from django.apps import apps
from django.test import TestCase

from brand.models import SiteContent

migration = import_module("brand.migrations.0019_add_careers_to_header_menu")

# The menu as it was saved before the careers page existed.
OLD_MENU = [
    {"label": "Research", "url": "/research/", "children": [
        {"label": "Artificial Intelligence", "url": "/research/#ai"},
    ]},
    {"label": "About", "url": "/about/", "children": [
        {"label": "Mission & Values", "url": "/about/#mission"},
        {"label": "Partnerships", "url": "/partnerships/"},
        {"label": "Volunteer & Learn", "url": "/about/#volunteer"},
    ]},
    {"label": "Blog", "url": "/blog/"},
]


class CareersMenuMigrationTests(TestCase):
    def setUp(self):
        self.content = SiteContent.objects.first() or SiteContent.objects.create()

    def run_forward(self, menu):
        self.content.header_links = menu
        self.content.save()
        migration.add_careers(apps, None)
        self.content.refresh_from_db()
        return self.content.header_links

    def about_labels(self, menu):
        return [c["label"] for l in menu if l["label"] == "About" for c in l["children"]]

    def test_careers_is_added_to_the_about_submenu_in_the_stored_menu(self):
        menu = self.run_forward([dict(l) for l in OLD_MENU])
        self.assertEqual(
            self.about_labels(menu),
            ["Mission & Values", "Partnerships", "Volunteer & Learn", "Careers & Jobs"],
        )
        careers = menu[1]["children"][-1]
        self.assertEqual(careers["url"], "/careers/")
        # Nothing else moved.
        self.assertEqual(menu[0], OLD_MENU[0])
        self.assertEqual(menu[2], OLD_MENU[2])

    def test_running_twice_does_not_duplicate_it(self):
        self.run_forward([dict(l) for l in OLD_MENU])
        migration.add_careers(apps, None)
        self.content.refresh_from_db()
        urls = [c["url"] for l in self.content.header_links for c in l.get("children", [])]
        self.assertEqual(urls.count("/careers/"), 1)

    def test_a_menu_that_already_links_careers_is_left_alone(self):
        menu = [{"label": "Join us", "url": "/careers"}] + [dict(l) for l in OLD_MENU]
        self.assertEqual(self.run_forward(menu), menu)

    def test_a_menu_without_an_about_submenu_is_left_alone(self):
        menu = [{"label": "Home", "url": "/"}, {"label": "About", "url": "/about/"}]
        self.assertEqual(self.run_forward(menu), menu)

    def test_company_submenu_from_the_code_default_is_recognised(self):
        menu = [
            {"label": "Company", "url": "/about/", "children": [
                {"label": "Mission & Values", "url": "/about/#mission"},
            ]},
        ]
        menu = self.run_forward(menu)
        self.assertEqual(menu[0]["children"][-1]["url"], "/careers/")

    def test_reverse_removes_only_the_added_link(self):
        self.run_forward([dict(l) for l in OLD_MENU])
        migration.remove_careers(apps, None)
        self.content.refresh_from_db()
        self.assertEqual(self.about_labels(self.content.header_links), [
            "Mission & Values", "Partnerships", "Volunteer & Learn",
        ])
