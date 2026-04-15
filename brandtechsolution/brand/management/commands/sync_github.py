from django.core.management.base import BaseCommand
from brand.models import Project
from brand.github_service import GitHubService
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Synchronizes GitHub repositories marked as synced in the database.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Starting GitHub sync for tracked projects...'))
        
        try:
            service = GitHubService()
        except ValueError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return

        # Fetch projects that are marked as synced
        synced_projects = Project.objects.filter(is_github_synced=True, github_repo_id__isnull=False)
        repo_ids = list(synced_projects.values_list('github_repo_id', flat=True))

        if not repo_ids:
            self.stdout.write(self.style.WARNING('No GitHub-synced projects found in the database.'))
            return

        self.stdout.write(f'Found {len(repo_ids)} project(s) to sync. Processing...')

        result = service.sync_repositories(repo_ids)

        if result.get("success"):
            self.stdout.write(self.style.SUCCESS(
                f'Successfully synced {result.get("synced_count")} repositories.'
            ))
            if result.get("error_count", 0) > 0:
                self.stdout.write(self.style.WARNING(
                    f'Encountered {result.get("error_count")} errors during sync.'
                ))
                for err in result.get("errors", []):
                    self.stdout.write(self.style.ERROR(err))
        else:
            self.stdout.write(self.style.ERROR(f'Sync failed: {result.get("error")}'))
            
        self.stdout.write(self.style.SUCCESS('Job complete.'))
