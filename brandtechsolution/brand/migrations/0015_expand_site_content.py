import brand.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brand", "0014_site_content"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_badge",
            field=models.CharField(default="ZERO-RATED SYLLABUS CDN", max_length=120),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_subtitle",
            field=models.CharField(default="EdTech SaaS Engine", max_length=180),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_feature_heading",
            field=models.CharField(
                default="Decentralized Syllabus Access for African Students",
                max_length=250,
            ),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_problem_label",
            field=models.CharField(default="The Problem:", max_length=100),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_problem_description",
            field=models.TextField(
                default="Students in African universities face prohibitive data costs and slow server connections, causing syllabus access bottlenecks during exam study cycles."
            ),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_solution_label",
            field=models.CharField(
                default="The Solution & Impact:", max_length=120
            ),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_solution_description",
            field=models.TextField(
                default="EduShare compresses and caches university study materials, reducing latency by 74% and serving over 50,000 active learners with zero offline interruptions."
            ),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_technology_heading",
            field=models.CharField(
                default="Technologies Powering EduShare:", max_length=160
            ),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_cta_label",
            field=models.CharField(default="Explore EduShare Africa", max_length=120),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_cta_url",
            field=models.CharField(default="/products/#edushare", max_length=500),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_technologies",
            field=models.JSONField(default=brand.models.default_flagship_technologies),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="flagship_stats",
            field=models.JSONField(default=brand.models.default_flagship_stats),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="capability_cards",
            field=models.JSONField(default=brand.models.default_capability_cards),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="technology_center_caption",
            field=models.CharField(
                default="PYTHON & REACT CENTERED", max_length=120
            ),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="technology_orbit",
            field=models.JSONField(default=brand.models.default_technology_orbit),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="technology_groups",
            field=models.JSONField(default=brand.models.default_technology_groups),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="why_cards",
            field=models.JSONField(default=brand.models.default_why_cards),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="journey_transparency_label",
            field=models.CharField(default="100% TRANSPARENT", max_length=100),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="journey_steps",
            field=models.JSONField(default=brand.models.default_journey_steps),
        ),
        migrations.AddField(
            model_name="sitecontent",
            name="impact_stats",
            field=models.JSONField(default=brand.models.default_impact_stats),
        ),
    ]
