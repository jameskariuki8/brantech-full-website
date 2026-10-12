from django.db import migrations

CAREERS = {"label": "Careers & Jobs", "url": "/careers/"}


def _links_to_careers(links):
    return any(
        link.get("url", "").rstrip("/") == "/careers"
        or _links_to_careers(link.get("children", []))
        for link in links
    )


def add_careers(apps, schema_editor):
    """Menus saved before the careers page existed never gain its default link.

    Adds Careers to the About / Company submenu of each stored header menu.
    A menu that already links to /careers/, or has no such submenu, is left
    alone, so an edited menu is never rearranged.
    """
    SiteContent = apps.get_model("brand", "SiteContent")
    for content in SiteContent.objects.all():
        links = content.header_links
        if not isinstance(links, list) or _links_to_careers(links):
            continue
        for link in links:
            is_about = (
                link.get("label", "").strip().lower() in {"about", "company"}
                or link.get("url", "").rstrip("/") == "/about"
            )
            if is_about and isinstance(link.get("children"), list):
                link["children"].append(dict(CAREERS))
                content.save(update_fields=["header_links"])
                break


def remove_careers(apps, schema_editor):
    SiteContent = apps.get_model("brand", "SiteContent")
    for content in SiteContent.objects.all():
        changed = False
        for link in content.header_links if isinstance(content.header_links, list) else []:
            children = link.get("children")
            if isinstance(children, list):
                kept = [c for c in children if c != CAREERS]
                changed = changed or len(kept) != len(children)
                link["children"] = kept
        if changed:
            content.save(update_fields=["header_links"])


class Migration(migrations.Migration):

    dependencies = [
        ("brand", "0018_partnerorganisation_partnershiptype"),
    ]

    operations = [
        migrations.RunPython(add_careers, remove_careers),
    ]
