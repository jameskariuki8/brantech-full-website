from django.db import migrations
from pgvector.django import VectorField

class Migration(migrations.Migration):

    dependencies = [
        ('brand', '0006_add_performance_indexes'),
    ]

    operations = [
        # Clear existing embeddings to allow dimension change
        migrations.RunSQL(
            sql='UPDATE brand_blogpost SET embedding = NULL;',
            reverse_sql=migrations.RunSQL.noop
        ),
        migrations.RunSQL(
            sql='UPDATE brand_project SET embedding = NULL;',
            reverse_sql=migrations.RunSQL.noop
        ),
        migrations.RunSQL(
            sql='ALTER TABLE brand_blogpost ALTER COLUMN embedding TYPE vector(3072);',
            reverse_sql='ALTER TABLE brand_blogpost ALTER COLUMN embedding TYPE vector(768);'
        ),
        migrations.RunSQL(
            sql='ALTER TABLE brand_project ALTER COLUMN embedding TYPE vector(3072);',
            reverse_sql='ALTER TABLE brand_project ALTER COLUMN embedding TYPE vector(768);'
        ),
        migrations.AlterField(
            model_name='blogpost',
            name='embedding',
            field=VectorField(blank=True, dimensions=3072, null=True),
        ),
        migrations.AlterField(
            model_name='project',
            name='embedding',
            field=VectorField(blank=True, dimensions=3072, null=True),
        ),
    ]
