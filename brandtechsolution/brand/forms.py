import re
from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from .models import Career, PartnerOrganisation, PartnershipType, SiteContent


def _safe_content_url(value, line_number):
    value = value.strip()
    if re.search(r"[\x00-\x20\\]", value):
        raise forms.ValidationError(f"Line {line_number}: the URL contains invalid characters.")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise forms.ValidationError(f"Line {line_number}: enter a valid URL.") from exc
    if value.startswith("/") and not value.startswith("//") and not parsed.netloc:
        return value
    if value.startswith("#"):
        return value
    if (
        parsed.scheme.lower() == "https"
        and parsed.netloc
        and parsed.username is None
        and parsed.password is None
    ):
        return value
    raise forms.ValidationError(
        f"Line {line_number}: use an https:// URL, a site path beginning with /, or a #section link."
    )


def _safe_image_url(value, line_number=1):
    url = _safe_content_url(value, line_number)
    if url.startswith("#"):
        raise forms.ValidationError("Use an image URL or a site path for images.")
    return url


def _parse_link_lines(value, *, with_icon=False):
    links = []
    for line_number, line in enumerate(value.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        expected_parts = 3 if with_icon else 2
        if len(parts) != expected_parts or not parts[0]:
            format_hint = "Label | URL | icon class" if with_icon else "Label | URL"
            raise forms.ValidationError(
                f"Line {line_number}: enter values in this format: {format_hint}."
            )
        link = {"label": parts[0], "url": _safe_content_url(parts[1], line_number)}
        if with_icon:
            if not re.fullmatch(r"[A-Za-z0-9 -]{1,80}", parts[2]):
                raise forms.ValidationError(
                    f"Line {line_number}: the icon class can contain letters, numbers, spaces, and hyphens only."
                )
            link["icon"] = parts[2]
        links.append(link)
    return links


def _validate_icon_class(value, line_number):
    if not re.fullmatch(r"[A-Za-z0-9 -]{1,80}", value):
        raise forms.ValidationError(
            f"Line {line_number}: icon classes can contain letters, numbers, spaces, and hyphens only."
        )
    return value


def _content_rows(value, expected_parts, format_hint):
    rows = []
    for line_number, line in enumerate(value.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != expected_parts:
            raise forms.ValidationError(
                f"Line {line_number}: enter values in this format: {format_hint}."
            )
        rows.append((line_number, parts))
    return rows


class SiteContentForm(forms.ModelForm):
    hero_title_before = forms.CharField(strip=False)
    hero_title_after = forms.CharField(strip=False)
    header_links_text = forms.CharField(
        label="Navigation links",
        required=False,
        widget=forms.Textarea(attrs={"rows": 12}),
        help_text=(
            "One link per line: Label | URL. Indent child links by two spaces under a menu item. "
            "Example: Products | /products/ then an indented EduShare Africa | /products/#edushare."
        ),
    )
    footer_quick_links_text = forms.CharField(
        label="Quick links",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="One link per line: Label | URL.",
    )
    footer_services_text = forms.CharField(
        label="Service links",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="One link per line: Label | URL.",
    )
    footer_legal_links_text = forms.CharField(
        label="Legal links",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="One link per line: Label | URL.",
    )
    footer_social_links_text = forms.CharField(
        label="Social links",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="One link per line: Label | URL | Font Awesome icon class.",
    )
    story_tabs_text = forms.CharField(
        label="Story tabs",
        required=False,
        widget=forms.Textarea(attrs={"rows": 9}),
        help_text=(
            "One tab per line: Tab label | Heading | Description | Quote | Attribution | Badge | Image URL. "
            "Keep at least one tab."
        ),
    )
    flagship_technologies_text = forms.CharField(
        label="Flagship technology badges",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="One badge per line: Label | Font Awesome icon class.",
    )
    flagship_stats_text = forms.CharField(
        label="Flagship impact statistics",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Keep four lines, one per existing statistic: Value | Label.",
    )
    capability_cards_text = forms.CharField(
        label="Capability cards",
        required=False,
        widget=forms.Textarea(attrs={"rows": 10}),
        help_text=(
            "Keep five lines in order: Badge | Title | Description | Image URL or site path | "
            "Font Awesome icon class | Technology 1~icon class; Technology 2~icon class."
        ),
    )
    technology_orbit_text = forms.CharField(
        label="Orbiting technology badges",
        required=False,
        widget=forms.Textarea(attrs={"rows": 10}),
        help_text="Keep ten lines in order: Label | Font Awesome icon class.",
    )
    technology_groups_text = forms.CharField(
        label="Technology categories",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Keep five lines in order: Category | Font Awesome icon class | Item 1; Item 2; Item 3.",
    )
    why_cards_text = forms.CharField(
        label="Why Teklora cards",
        required=False,
        widget=forms.Textarea(attrs={"rows": 8}),
        help_text=(
            "Keep four lines in order: Image URL or site path | Image description | Badge | "
            "Title | Description."
        ),
    )
    journey_steps_text = forms.CharField(
        label="Engineering journey steps",
        required=False,
        widget=forms.Textarea(attrs={"rows": 14}),
        help_text=(
            "Keep seven lines in order: Menu label | Badge | Title | Summary | "
            "Deliverable 1; Deliverable 2 | Accent color (#RRGGBB) | Image URL or site path."
        ),
    )
    impact_stats_text = forms.CharField(
        label="Landing-page impact metrics",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Keep four lines in order: Numeric target | Label. Satisfaction is displayed as a percentage.",
    )

    class Meta:
        model = SiteContent
        fields = [
            "brand_name",
            "logo_url",
            "header_links_text",
            "header_cta_label",
            "header_cta_url",
            "footer_description",
            "footer_quick_heading",
            "footer_services_heading",
            "footer_contact_heading",
            "footer_quick_links_text",
            "footer_services_text",
            "footer_legal_links_text",
            "footer_social_links_text",
            "contact_email",
            "contact_phone",
            "copyright_text",
            "landing_title",
            "landing_meta_description",
            "hero_title_before",
            "hero_title_highlight",
            "hero_title_after",
            "hero_description",
            "hero_quote",
            "hero_primary_label",
            "hero_primary_url",
            "hero_secondary_label",
            "hero_secondary_url",
            "hero_image_url",
            "hero_scroll_label",
            "story_label",
            "story_heading",
            "story_tabs_text",
            "flagship_label",
            "flagship_title",
            "flagship_description",
            "flagship_image_url",
            "flagship_badge",
            "flagship_subtitle",
            "flagship_feature_heading",
            "flagship_problem_label",
            "flagship_problem_description",
            "flagship_solution_label",
            "flagship_solution_description",
            "flagship_technology_heading",
            "flagship_cta_label",
            "flagship_cta_url",
            "flagship_technologies_text",
            "flagship_stats_text",
            "capabilities_label",
            "capabilities_heading",
            "capabilities_description",
            "capability_cards_text",
            "technology_label",
            "technology_heading",
            "technology_description",
            "technology_center_caption",
            "technology_orbit_text",
            "technology_groups_text",
            "why_label",
            "why_heading",
            "why_cards_text",
            "journey_label",
            "journey_heading",
            "journey_description",
            "journey_transparency_label",
            "journey_steps_text",
            "impact_label",
            "impact_heading",
            "impact_stats_text",
        ]
        labels = {
            "brand_name": "Brand name",
            "logo_url": "Logo image URL or site path",
            "header_cta_url": "Header button URL",
            "landing_title": "Browser and search title",
            "landing_meta_description": "Search description",
            "hero_title_before": "Headline · text before highlight",
            "hero_title_highlight": "Headline · highlighted text",
            "hero_title_after": "Headline · text after highlight",
            "hero_primary_url": "Primary button URL",
            "hero_secondary_url": "Secondary button URL",
            "hero_image_url": "Hero image URL or site path",
            "flagship_image_url": "Flagship image URL or site path",
            "flagship_cta_url": "Flagship button URL",
        }
        help_texts = {
            "logo_url": "Use a path such as /static/brand/images/logo.png or an https:// image URL.",
            "landing_meta_description": "Short summary shown in search results and link previews.",
            "hero_title_before": "Keep the trailing space if the highlighted words need a gap.",
            "hero_title_after": "Keep the leading space if the highlighted words need a gap.",
            "hero_image_url": "Use a path such as /media/hero.jpg or an https:// image URL.",
            "flagship_image_url": "Use a path such as /media/product.jpg or an https:// image URL.",
            "flagship_cta_url": "Use a path beginning with /, an https:// URL, or a #section link.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        content = self.instance
        if not self.is_bound:
            self.initial.update({
                "header_links_text": self._format_navigation_links(content.header_links),
                "footer_quick_links_text": self._format_links(content.footer_quick_links),
                "footer_services_text": self._format_links(content.footer_services),
                "footer_legal_links_text": self._format_links(content.footer_legal_links),
                "footer_social_links_text": self._format_links(
                    content.footer_social_links, with_icon=True
                ),
                "story_tabs_text": self._format_story_tabs(content.story_tabs),
                "flagship_technologies_text": self._format_records(
                    content.flagship_technologies, ("label", "icon")
                ),
                "flagship_stats_text": self._format_records(
                    content.flagship_stats, ("value", "label")
                ),
                "capability_cards_text": self._format_records(
                    content.capability_cards,
                    ("badge", "title", "description", "image", "icon", "technologies"),
                    list_keys=("technologies",),
                ),
                "technology_orbit_text": self._format_records(
                    content.technology_orbit, ("label", "icon")
                ),
                "technology_groups_text": self._format_records(
                    content.technology_groups, ("label", "icon", "items"),
                    list_keys=("items",),
                ),
                "why_cards_text": self._format_records(
                    content.why_cards, ("image", "alt", "badge", "title", "description")
                ),
                "journey_steps_text": self._format_records(
                    content.journey_steps,
                    ("label", "tagline", "title", "summary", "deliverables", "color", "image"),
                    list_keys=("deliverables",),
                ),
                "impact_stats_text": self._format_records(
                    content.impact_stats, ("value", "label")
                ),
            })
        self.groups = [
            ("Header", [self[name] for name in ["brand_name", "logo_url", "header_links_text", "header_cta_label", "header_cta_url"]]),
            ("Footer", [self[name] for name in ["footer_description", "footer_quick_heading", "footer_quick_links_text", "footer_services_heading", "footer_services_text", "footer_legal_links_text", "footer_contact_heading", "footer_social_links_text", "contact_email", "contact_phone", "copyright_text"]]),
            ("Landing page · Search preview", [self["landing_title"], self["landing_meta_description"]]),
            ("Landing page · Hero", [self[name] for name in ["hero_title_before", "hero_title_highlight", "hero_title_after", "hero_description", "hero_quote", "hero_primary_label", "hero_primary_url", "hero_secondary_label", "hero_secondary_url", "hero_image_url", "hero_scroll_label"]]),
            ("Landing page · Story", [self[name] for name in ["story_label", "story_heading", "story_tabs_text"]]),
            ("Landing page · Flagship", [self[name] for name in ["flagship_label", "flagship_title", "flagship_description", "flagship_image_url", "flagship_badge", "flagship_subtitle", "flagship_feature_heading", "flagship_problem_label", "flagship_problem_description", "flagship_solution_label", "flagship_solution_description", "flagship_technology_heading", "flagship_cta_label", "flagship_cta_url", "flagship_technologies_text", "flagship_stats_text"]]),
            ("Landing page · Capabilities", [self[name] for name in ["capabilities_label", "capabilities_heading", "capabilities_description", "capability_cards_text"]]),
            ("Landing page · Technology", [self[name] for name in ["technology_label", "technology_heading", "technology_description", "technology_center_caption", "technology_orbit_text", "technology_groups_text"]]),
            ("Landing page · Why Teklora", [self[name] for name in ["why_label", "why_heading", "why_cards_text"]]),
            ("Landing page · Engineering journey", [self[name] for name in ["journey_label", "journey_heading", "journey_description", "journey_transparency_label", "journey_steps_text"]]),
            ("Landing page · Impact", [self[name] for name in ["impact_label", "impact_heading", "impact_stats_text"]]),
        ]
        for field in self.fields.values():
            field.widget.attrs.setdefault(
                "class",
                "w-full rounded-xl border border-white/10 bg-[#080D16] px-4 py-3 text-sm text-white placeholder:text-gray-600 focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/20",
            )

    @staticmethod
    def _format_links(links, *, with_icon=False):
        if not isinstance(links, list):
            return ""
        rows = []
        for link in links:
            if not isinstance(link, dict):
                continue
            values = [link.get("label", ""), link.get("url", "")]
            if with_icon:
                values.append(link.get("icon", ""))
            rows.append(" | ".join(values))
        return "\n".join(rows)

    @staticmethod
    def _format_navigation_links(links):
        if not isinstance(links, list):
            return ""
        rows = []
        for link in links:
            if not isinstance(link, dict):
                continue
            rows.append(f"{link.get('label', '')} | {link.get('url', '')}")
            for child in link.get("children", []):
                if isinstance(child, dict):
                    rows.append(f"  {child.get('label', '')} | {child.get('url', '')}")
        return "\n".join(rows)

    @staticmethod
    def _format_story_tabs(tabs):
        if not isinstance(tabs, list):
            return ""
        return "\n".join(
            " | ".join(
                str(tab.get(key, ""))
                for key in ("label", "title", "desc", "quote", "author", "badgeText", "image")
            )
            for tab in tabs
            if isinstance(tab, dict)
        )

    @staticmethod
    def _format_records(records, keys, *, list_keys=()):
        if not isinstance(records, list):
            return ""
        rows = []
        for record in records:
            if not isinstance(record, dict):
                continue
            values = []
            for key in keys:
                value = record.get(key, "")
                if key in list_keys and isinstance(value, list):
                    if value and isinstance(value[0], dict):
                        value = "; ".join(
                            f"{item.get('label', '')}~{item.get('icon', '')}"
                            for item in value
                            if isinstance(item, dict)
                        )
                    else:
                        value = "; ".join(str(item) for item in value)
                values.append(str(value))
            rows.append(" | ".join(values))
        return "\n".join(rows)

    def clean_header_links_text(self):
        links = []
        parent = None
        for line_number, line in enumerate(
            self.cleaned_data["header_links_text"].splitlines(), start=1
        ):
            if not line.strip():
                continue
            indented = line.startswith((" ", "\t"))
            parts = [part.strip() for part in line.strip().split("|")]
            if len(parts) != 2 or not parts[0]:
                raise forms.ValidationError(
                    f"Line {line_number}: enter each navigation link as Label | URL."
                )
            link = {
                "label": parts[0],
                "url": _safe_content_url(parts[1], line_number),
            }
            if indented:
                if parent is None:
                    raise forms.ValidationError(
                        f"Line {line_number}: indent a submenu link under a top-level navigation link."
                    )
                parent.setdefault("children", []).append(link)
            else:
                links.append(link)
                parent = link
        return links

    def clean_footer_quick_links_text(self):
        return _parse_link_lines(self.cleaned_data["footer_quick_links_text"])

    def clean_footer_services_text(self):
        return _parse_link_lines(self.cleaned_data["footer_services_text"])

    def clean_footer_legal_links_text(self):
        return _parse_link_lines(self.cleaned_data["footer_legal_links_text"])

    def clean_footer_social_links_text(self):
        return _parse_link_lines(
            self.cleaned_data["footer_social_links_text"], with_icon=True
        )

    def clean_story_tabs_text(self):
        tabs = []
        for line_number, line in enumerate(
            self.cleaned_data["story_tabs_text"].splitlines(), start=1
        ):
            if not line.strip():
                continue
            parts = [part.strip() for part in line.split("|", 6)]
            if len(parts) != 7 or not parts[0] or not parts[1]:
                raise forms.ValidationError(
                    f"Line {line_number}: enter Tab label | Heading | Description | Quote | Attribution | Badge | Image URL."
                )
            tabs.append({
                "label": parts[0],
                "title": parts[1],
                "desc": parts[2],
                "quote": parts[3],
                "author": parts[4],
                "badgeText": parts[5],
                "image": _safe_image_url(parts[6], line_number),
            })
        if not tabs:
            raise forms.ValidationError("Add at least one story tab.")
        return tabs

    @staticmethod
    def _require_row_count(rows, expected, section):
        if len(rows) != expected:
            raise forms.ValidationError(
                f"Keep exactly {expected} existing entries in {section} so the landing-page layout stays intact."
            )

    def clean_flagship_technologies_text(self):
        rows = _content_rows(
            self.cleaned_data["flagship_technologies_text"],
            2,
            "Label | Font Awesome icon class",
        )
        if not rows or len(rows) > 8:
            raise forms.ValidationError("Add between one and eight technology badges.")
        return [
            {
                "label": parts[0],
                "icon": _validate_icon_class(parts[1], line_number),
            }
            for line_number, parts in rows
        ]

    def clean_flagship_stats_text(self):
        rows = _content_rows(
            self.cleaned_data["flagship_stats_text"], 2, "Value | Label"
        )
        self._require_row_count(rows, 4, "flagship statistics")
        if any(not parts[0] or not parts[1] for _, parts in rows):
            raise forms.ValidationError("Each flagship statistic needs a value and label.")
        return [{"value": parts[0], "label": parts[1]} for _, parts in rows]

    def clean_capability_cards_text(self):
        rows = _content_rows(
            self.cleaned_data["capability_cards_text"],
            6,
            "Badge | Title | Description | Image URL | icon class | Technology 1~icon class; Technology 2~icon class",
        )
        self._require_row_count(rows, 5, "capability cards")
        cards = []
        for line_number, parts in rows:
            badge, title, description, image, icon, technologies = parts
            tech_items = []
            for item in technologies.split(";"):
                if not item.strip():
                    continue
                tag_parts = [part.strip() for part in item.split("~")]
                if len(tag_parts) != 2 or not tag_parts[0]:
                    raise forms.ValidationError(
                        f"Line {line_number}: enter each technology as Label~icon class."
                    )
                tech_items.append({
                    "label": tag_parts[0],
                    "icon": _validate_icon_class(tag_parts[1], line_number),
                })
            if not badge or not title or not description or not tech_items:
                raise forms.ValidationError(
                    f"Line {line_number}: each card needs a badge, title, description, and at least one technology."
                )
            cards.append({
                "badge": badge,
                "title": title,
                "description": description,
                "image": _safe_image_url(image, line_number),
                "icon": _validate_icon_class(icon, line_number),
                "technologies": tech_items,
            })
        return cards

    def clean_technology_orbit_text(self):
        rows = _content_rows(
            self.cleaned_data["technology_orbit_text"],
            2,
            "Label | Font Awesome icon class",
        )
        self._require_row_count(rows, 10, "orbiting technology badges")
        return [
            {"label": parts[0], "icon": _validate_icon_class(parts[1], line_number)}
            for line_number, parts in rows
        ]

    def clean_technology_groups_text(self):
        rows = _content_rows(
            self.cleaned_data["technology_groups_text"],
            3,
            "Category | Font Awesome icon class | Item 1; Item 2",
        )
        self._require_row_count(rows, 5, "technology categories")
        categories = []
        for line_number, parts in rows:
            label, icon, items = parts
            item_list = [item.strip() for item in items.split(";") if item.strip()]
            if not label or not item_list:
                raise forms.ValidationError(
                    f"Line {line_number}: each category needs a name and at least one technology."
                )
            categories.append({
                "label": label,
                "icon": _validate_icon_class(icon, line_number),
                "items": item_list,
            })
        return categories

    def clean_why_cards_text(self):
        rows = _content_rows(
            self.cleaned_data["why_cards_text"],
            5,
            "Image URL | Image description | Badge | Title | Description",
        )
        self._require_row_count(rows, 4, "Why Teklora cards")
        cards = []
        for line_number, parts in rows:
            image, alt, badge, title, description = parts
            if not all((alt, badge, title, description)):
                raise forms.ValidationError(
                    f"Line {line_number}: each card needs an image description, badge, title, and description."
                )
            cards.append({
                "image": _safe_image_url(image, line_number),
                "alt": alt,
                "badge": badge,
                "title": title,
                "description": description,
            })
        return cards

    def clean_journey_steps_text(self):
        rows = _content_rows(
            self.cleaned_data["journey_steps_text"],
            7,
            "Menu label | Badge | Title | Summary | Deliverables | Accent color | Image URL",
        )
        self._require_row_count(rows, 7, "engineering journey steps")
        steps = []
        for line_number, parts in rows:
            label, tagline, title, summary, deliverables, color, image = parts
            deliverable_list = [
                item.strip() for item in deliverables.split(";") if item.strip()
            ]
            if not all((label, tagline, title, summary)) or not deliverable_list:
                raise forms.ValidationError(
                    f"Line {line_number}: each step needs a menu label, badge, title, summary, and deliverable."
                )
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                raise forms.ValidationError(
                    f"Line {line_number}: use a six-digit hex color such as #00FF94."
                )
            steps.append({
                "label": label,
                "tagline": tagline,
                "title": title,
                "summary": summary,
                "deliverables": deliverable_list,
                "color": color,
                "image": _safe_image_url(image, line_number),
            })
        return steps

    def clean_impact_stats_text(self):
        rows = _content_rows(
            self.cleaned_data["impact_stats_text"], 2, "Numeric target | Label"
        )
        self._require_row_count(rows, 4, "landing-page impact metrics")
        keys = (
            "metricProjects",
            "metricClients",
            "metricTech",
            "metricSatisfaction",
        )
        stats = []
        for (line_number, parts), key in zip(rows, keys):
            if not parts[0].isdigit() or int(parts[0]) > 1000000 or not parts[1]:
                raise forms.ValidationError(
                    f"Line {line_number}: enter a number up to 1,000,000 and a metric label."
                )
            stats.append({"key": key, "value": int(parts[0]), "label": parts[1]})
        return stats

    def clean_logo_url(self):
        return _safe_image_url(self.cleaned_data["logo_url"])

    def clean_hero_image_url(self):
        return _safe_image_url(self.cleaned_data["hero_image_url"])

    def clean_flagship_image_url(self):
        return _safe_image_url(self.cleaned_data["flagship_image_url"])

    def clean_flagship_cta_url(self):
        return _safe_content_url(self.cleaned_data["flagship_cta_url"], 1)

    def clean_flagship_badge(self):
        return self.cleaned_data["flagship_badge"].strip()

    def clean_header_cta_url(self):
        return _safe_content_url(self.cleaned_data["header_cta_url"], 1)

    def clean_hero_primary_url(self):
        return _safe_content_url(self.cleaned_data["hero_primary_url"], 1)

    def clean_hero_secondary_url(self):
        return _safe_content_url(self.cleaned_data["hero_secondary_url"], 1)

    def clean_contact_phone(self):
        phone = self.cleaned_data["contact_phone"].strip()
        if not re.fullmatch(r"[+0-9(). -]+", phone) or not re.search(r"\d", phone):
            raise forms.ValidationError("Enter a phone number using digits and common phone punctuation.")
        return phone

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.header_links = self.cleaned_data["header_links_text"]
        instance.footer_quick_links = self.cleaned_data["footer_quick_links_text"]
        instance.footer_services = self.cleaned_data["footer_services_text"]
        instance.footer_legal_links = self.cleaned_data["footer_legal_links_text"]
        instance.footer_social_links = self.cleaned_data["footer_social_links_text"]
        instance.story_tabs = self.cleaned_data["story_tabs_text"]
        instance.flagship_technologies = self.cleaned_data["flagship_technologies_text"]
        instance.flagship_stats = self.cleaned_data["flagship_stats_text"]
        instance.capability_cards = self.cleaned_data["capability_cards_text"]
        instance.technology_orbit = self.cleaned_data["technology_orbit_text"]
        instance.technology_groups = self.cleaned_data["technology_groups_text"]
        instance.why_cards = self.cleaned_data["why_cards_text"]
        instance.journey_steps = self.cleaned_data["journey_steps_text"]
        instance.impact_stats = self.cleaned_data["impact_stats_text"]
        if commit:
            instance.save()
        return instance


# ---------------------------------------------------------------------------
# Partnerships & People: the panel's editors for the records behind
# /partnerships/ and /careers/.
# ---------------------------------------------------------------------------

# Theme-variable classes, so the editors follow the panel's light and dark
# themes. An opacity suffix on these (bg-surface/50) draws nothing: Tailwind
# cannot add alpha to a colour defined as a CSS variable.
PANEL_INPUT_CLASS = (
    "w-full rounded-xl border border-borderLight bg-background px-4 py-3 text-sm text-primaryText "
    "placeholder:text-secondaryText focus:border-brandBlue focus:outline-none focus:ring-2 "
    "focus:ring-sky-500/20"
)
PANEL_FILE_CLASS = (
    "block w-full text-sm text-secondaryText file:mr-3 file:rounded-lg file:border-0 "
    "file:bg-black/5 dark:file:bg-white/10 file:px-4 file:py-2 file:text-sm file:font-semibold "
    "file:text-primaryText hover:file:bg-black/10 dark:hover:file:bg-white/20"
)
PANEL_CHECKBOX_CLASS = "h-4 w-4 rounded border-borderLight accent-sky-500"

ICON_PATTERN = re.compile(r"^(fas|far|fab|fa-solid|fa-regular|fa-brands) fa-[a-z0-9-]+$")
ACCENT_CHOICES = [
    ("blue", "Blue"),
    ("amber", "Amber"),
    ("emerald", "Emerald"),
    ("purple", "Purple"),
    ("rose", "Rose"),
]
LOGO_MAX_BYTES = 2 * 1024 * 1024
DOCUMENT_MAX_BYTES = 10 * 1024 * 1024
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx")


def _web_url(value):
    """Allow only http(s) links: these end up in public href and src attributes."""
    if value and urlsplit(value).scheme.lower() not in ("http", "https"):
        raise forms.ValidationError("Use a link starting with https:// or http://.")
    return value


class PanelFormMixin:
    """Gives every widget the panel's dark input styling."""

    def style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = PANEL_CHECKBOX_CLASS
            elif isinstance(widget, forms.ClearableFileInput):
                css = PANEL_FILE_CLASS
            else:
                css = PANEL_INPUT_CLASS
            widget.attrs.setdefault("class", css)


class PartnershipTypeForm(PanelFormMixin, forms.ModelForm):
    accent = forms.ChoiceField(
        choices=ACCENT_CHOICES, help_text="Colours the icon and summary on the track card."
    )

    class Meta:
        model = PartnershipType
        fields = [
            "title", "tagline", "description", "benefits", "requirements",
            "status", "icon", "accent", "order",
        ]
        labels = {
            "title": "Track name",
            "tagline": "One-line summary",
            "benefits": "What partners get",
            "requirements": "Who can apply",
            "order": "Display order",
        }
        help_texts = {
            "tagline": "Shown under the track name on the card.",
            "benefits": "One per line.",
            "requirements": "One per line.",
            "icon": "A Font Awesome class, for example fas fa-university. Shown on the track card.",
            "order": "Lower numbers are shown first.",
            "status": "Closed tracks are listed separately as not recruiting.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "benefits": forms.Textarea(attrs={"rows": 5}),
            "requirements": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_icon(self):
        icon = " ".join(self.cleaned_data["icon"].split())
        if not ICON_PATTERN.match(icon):
            raise forms.ValidationError("Use a Font Awesome class such as fas fa-handshake.")
        return icon


class PartnerOrganisationForm(PanelFormMixin, forms.ModelForm):
    class Meta:
        model = PartnerOrganisation
        fields = [
            "name", "sector", "website", "joined_at", "description", "logo",
            "logo_url", "order", "featured",
        ]
        labels = {
            "logo": "Logo upload",
            "logo_url": "Or a logo link",
            "featured": "Show in the partners strip",
            "order": "Display order",
            "joined_at": "Partner since",
        }
        help_texts = {
            "logo": "PNG, JPG or WebP, up to 2 MB. An upload is used before a logo link.",
            "website": "",
            "joined_at": "",
            "featured": "Untick to keep the partner saved but off the public page.",
            "logo_url": "Used only when no logo is uploaded.",
            "description": "A short line about the partner.",
            "order": "Lower numbers are shown first.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "joined_at": forms.DateInput(
                attrs={"type": "date", "class": PANEL_INPUT_CLASS + " dark:[color-scheme:dark]"},
                format="%Y-%m-%d",
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_website(self):
        return _web_url(self.cleaned_data["website"])

    def clean_logo_url(self):
        return _web_url(self.cleaned_data["logo_url"])

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        # Only a new upload is checked; the stored file was accepted earlier.
        if isinstance(logo, UploadedFile) and logo.size > LOGO_MAX_BYTES:
            raise forms.ValidationError("The logo is larger than 2 MB.")
        return logo


class CareerForm(PanelFormMixin, forms.ModelForm):
    class Meta:
        model = Career
        fields = ["title", "employment_type", "location", "email", "status", "description", "document"]
        labels = {
            "title": "Job title",
            "employment_type": "Type",
            "email": "Applications go to",
            "document": "Job description file",
        }
        help_texts = {
            "employment_type": "For example Full-time, Part-time, Contract or Internship.",
            "document": "Optional. PDF, DOC or DOCX, up to 10 MB.",
            "description": "Line breaks are kept on the careers page.",
            "email": f"Must end in @{settings.MAILBOX_DOMAIN}: only mail that reaches us can be "
                     "answered automatically once the role closes.",
            "status": "Closed roles leave the careers page, and anyone who still applies "
                      "gets an email saying applications have closed.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_document(self):
        document = self.cleaned_data.get("document")
        # Only a new upload is checked; the stored file was accepted earlier.
        if isinstance(document, UploadedFile):
            if not document.name.lower().endswith(DOCUMENT_EXTENSIONS):
                raise forms.ValidationError("Upload a PDF, DOC or DOCX file.")
            if document.size > DOCUMENT_MAX_BYTES:
                raise forms.ValidationError("The file is larger than 10 MB.")
        return document
