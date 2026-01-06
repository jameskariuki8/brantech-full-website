"""
Migration to add embedding fields to BlogPost and Project models.
Uses pgvector's VectorField for storing embeddings.
"""
from django.db import migrations
from pgvector.django import VectorField


class Migration(migrations.Migration):
    
    dependencies = [
        ('brand', '0004_install_pgvector_extension'),
    ]

    operations = [
        migrations.AddField(
            model_name='blogpost',
            name='embedding',
            field=VectorField(dimensions=768, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='project',
            name='embedding',
            field=VectorField(dimensions=768, null=True, blank=True),
        ),
    ]
