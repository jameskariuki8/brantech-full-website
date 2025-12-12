from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Seeds the database with initial admin users'

    def handle(self, *args, **kwargs):
        admins = [
            'info@brantechsolutions.co',
            'admin@brantechsolutions.co'
        ]
        password = 'TekLora@admin'

        for email in admins:
            if not User.objects.filter(username=email).exists():
                User.objects.create_superuser(username=email, email=email, password=password)
                self.stdout.write(self.style.SUCCESS(f'Successfully created admin: {email}'))
            else:
                self.stdout.write(self.style.WARNING(f'Admin already exists: {email}'))
