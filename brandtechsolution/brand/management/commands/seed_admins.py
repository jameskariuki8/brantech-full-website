import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Seeds the database with initial admin users. The password is read '
        'from the SEED_ADMIN_PASSWORD environment variable.'
    )

    def handle(self, *args, **kwargs):
        admins = [
            'info@brantechsolutions.co',
            'admin@brantechsolutions.co'
        ]

        # Previously hardcoded. These are superuser accounts on a public site
        # and this repository is public, so the literal was a disclosed
        # credential for every account ever seeded with it - and it stayed
        # valid until someone changed it by hand. Failing loudly is better
        # than a default, which would just become the next shared secret.
        password = os.environ.get('SEED_ADMIN_PASSWORD')
        if not password:
            raise CommandError(
                'SEED_ADMIN_PASSWORD is not set. Refusing to create superuser '
                'accounts with a default password. Set it to a strong value '
                'for this deployment and re-run.'
            )

        for email in admins:
            if not User.objects.filter(username=email).exists():
                User.objects.create_superuser(username=email, email=email, password=password)
                self.stdout.write(self.style.SUCCESS(f'Successfully created admin: {email}'))
            else:
                self.stdout.write(self.style.WARNING(f'Admin already exists: {email}'))
