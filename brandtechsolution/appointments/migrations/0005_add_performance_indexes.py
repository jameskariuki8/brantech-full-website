# Generated migration to add performance indexes for appointments

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0004_alter_appointment_title'),
    ]

    operations = [
        # Add indexes for Appointment model
        migrations.AddIndex(
            model_name='appointment',
            index=models.Index(fields=['date'], name='appt_date_idx'),
        ),
        migrations.AddIndex(
            model_name='appointment',
            index=models.Index(fields=['status'], name='appt_status_idx'),
        ),
        migrations.AddIndex(
            model_name='appointment',
            index=models.Index(fields=['date', 'status'], name='appt_date_status_idx'),
        ),
        migrations.AddIndex(
            model_name='appointment',
            index=models.Index(fields=['-created_at'], name='appt_created_idx'),
        ),
    ]
