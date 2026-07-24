"""
Migration to install the pgvector extension in PostgreSQL.
This must run before any migrations that use VectorField.
"""
from django.db import migrations


def install_pgvector(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS vector;')

def remove_pgvector(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('DROP EXTENSION IF EXISTS vector;')

class Migration(migrations.Migration):
    
    dependencies = [
        ('brand', '0003_remove_project_budget_remove_project_client_and_more'),
    ]

    operations = [
        migrations.RunPython(install_pgvector, remove_pgvector),
    ]
