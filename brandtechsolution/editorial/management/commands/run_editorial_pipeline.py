from django.core.management.base import BaseCommand
from editorial.orchestrator import EditorialPipelineOrchestrator


class Command(BaseCommand):
    help = 'Executes Teklora Autonomous AI Newsroom Pipeline'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=1, help='Number of articles to generate')
        parser.add_argument('--auto-publish', action='store_true', help='Auto publish without editor review')
        parser.add_argument('--priority-threshold', type=float, default=6.5, help='Minimum priority score required')

    def handle(self, *args, **options):
        limit = options['limit']
        auto_publish = options['auto_publish']
        threshold = options['priority_threshold']

        self.stdout.write(self.style.SUCCESS(f"Starting Teklora Autonomous Pipeline (limit={limit}, auto_publish={auto_publish}, threshold={threshold})..."))

        orchestrator = EditorialPipelineOrchestrator(priority_threshold=threshold)
        articles = orchestrator.run_full_autonomous_cycle(limit=limit, auto_publish=auto_publish)

        self.stdout.write(self.style.SUCCESS(f"[OK] Cycle complete. {len(articles)} articles generated."))
        for a in articles:
            self.stdout.write(f" - [{a.status.upper()}] #{a.id}: {a.title}")
