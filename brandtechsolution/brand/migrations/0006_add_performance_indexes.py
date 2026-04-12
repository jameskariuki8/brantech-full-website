# Generated migration to add performance indexes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brand', '0005_add_embedding_fields'),
    ]

    operations = [
        # Add indexes for BlogPost
        migrations.AddIndex(
            model_name='blogpost',
            index=models.Index(fields=['-created_at'], name='brand_blogpost_created_idx'),
        ),
        migrations.AddIndex(
            model_name='blogpost',
            index=models.Index(fields=['-updated_at'], name='brand_blogpost_updated_idx'),
        ),
        migrations.AddIndex(
            model_name='blogpost',
            index=models.Index(fields=['featured'], name='brand_blogpost_featured_idx'),
        ),
        migrations.AddIndex(
            model_name='blogpost',
            index=models.Index(fields=['category'], name='brand_blogpost_category_idx'),
        ),
        
        # Add indexes for Project
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['-created_at'], name='brand_project_created_idx'),
        ),
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['-updated_at'], name='brand_project_updated_idx'),
        ),
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['featured'], name='brand_project_featured_idx'),
        ),
        
        # Add indexes for Event
        migrations.AddIndex(
            model_name='event',
            index=models.Index(fields=['date'], name='brand_event_date_idx'),
        ),
        migrations.AddIndex(
            model_name='event',
            index=models.Index(fields=['featured'], name='brand_event_featured_idx'),
        ),
        migrations.AddIndex(
            model_name='event',
            index=models.Index(fields=['event_type'], name='brand_event_type_idx'),
        ),
    ]
