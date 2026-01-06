"""
Migration to install the pgvector extension in PostgreSQL.
This must run before any migrations that use VectorField.
"""
from django.db import migrations


class Migration(migrations.Migration):
    
    dependencies = [
        ('brand', '0003_remove_project_budget_remove_project_client_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE EXTENSION IF NOT EXISTS vector;',
            reverse_sql='DROP EXTENSION IF EXISTS vector;',
        ),
    ]
