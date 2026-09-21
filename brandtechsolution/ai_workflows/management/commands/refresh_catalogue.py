"""Verify the providers and refresh the model catalogue.

    manage.py refresh_catalogue
    manage.py refresh_catalogue --provider gemini
"""
from django.core.management.base import BaseCommand

from ai_workflows.harness.catalogue import refresh
from ai_workflows.models import CatalogueEntry, Provider


class Command(BaseCommand):
    help = "Verify provider credentials and refresh the model catalogue."

    def add_arguments(self, parser):
        parser.add_argument('--provider', action='append', dest='providers',
                            help="Limit to this provider; repeatable.")

    def handle(self, *args, **options):
        result = refresh(providers=options['providers'])

        self.stdout.write("\nProviders")
        self.stdout.write("=" * 60)
        for provider in Provider.objects.all():
            style = {
                Provider.ACTIVE: self.style.SUCCESS,
                Provider.CANDIDATE: self.style.WARNING,
                Provider.ABSENT: self.style.NOTICE,
            }[provider.status]
            count = CatalogueEntry.objects.filter(
                provider=provider.name, available=True).count()
            suffix = f" -- {provider.last_error}" if provider.last_error else ""
            flag = "" if provider.enabled else "  [disabled]"
            self.stdout.write(style(
                f"  {provider.name:12} {provider.status:10} {count:4} models"
                f"{flag}{suffix}"
            ))

        priced = CatalogueEntry.objects.exclude(price_source=CatalogueEntry.UNKNOWN)
        self.stdout.write("\nPricing")
        self.stdout.write("-" * 60)
        for source, _label in CatalogueEntry.PRICE_SOURCE_CHOICES:
            n = CatalogueEntry.objects.filter(price_source=source).count()
            if n:
                self.stdout.write(f"  {source:12} {n:5} models")

        total = CatalogueEntry.objects.count()
        self.stdout.write(
            f"\n  {priced.count()}/{total} models have a price "
            f"({result['borrowed']} borrowed from OpenRouter, "
            f"{result['manual']} from the checked-in table)"
        )
