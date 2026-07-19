from django.db import migrations


def backfill_body_source(apps, schema_editor):
    """Existing rows hold un-inlined authored HTML, so it is a valid source."""
    for model_name in ("EmailTemplate", "Campaign"):
        model = apps.get_model("messaging", model_name)
        for obj in model.objects.exclude(body_html="").filter(body_source=""):
            obj.body_source = obj.body_html
            obj.save(update_fields=["body_source"])


def noop_reverse(apps, schema_editor):
    """Reversing drops nothing: body_source is additive."""


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0007_campaign_body_source_emailtemplate_body_source"),
    ]

    operations = [
        migrations.RunPython(backfill_body_source, noop_reverse),
    ]
