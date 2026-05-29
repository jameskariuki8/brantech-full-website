from django.db import migrations, models
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    BlogPost = apps.get_model("brand", "BlogPost")
    for post in BlogPost.objects.all():
        if post.slug:
            continue
        base = slugify(post.title)[:200] or "post"  # 200 leaves room for "-N" suffix (field max=220)
        slug = base
        n = 2
        while BlogPost.objects.exclude(pk=post.pk).filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        post.slug = slug
        post.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("brand", "0008_remove_blogpost_brand_blogpost_created_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="blogpost",
            name="slug",
            field=models.CharField(max_length=220, null=True, blank=True),
        ),
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="blogpost",
            name="slug",
            field=models.SlugField(max_length=220, unique=True, blank=True),
        ),
    ]
