from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Executes Teklora Autonomous AI Newsroom Pipeline'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=1, help='Number of articles to generate')
        parser.add_argument('--auto-publish', action='store_true', help='Auto publish without editor review')
        parser.add_argument('--priority-threshold', type=float, default=6.5, help='Minimum priority score required')

    def handle(self, *args, **options):
        # Dispatched through the supervisor, like the Celery task, so a cycle
        # run by hand records the newsroom's health the same way a scheduled
        # one does. Two entry points that disagree about whether failures are
        # recorded would make the health table depend on who started the run.
        from ai_workflows.harness.supervisor import Supervisor

        limit = options['limit']
        auto_publish = options['auto_publish']
        threshold = options['priority_threshold']

        self.stdout.write(self.style.SUCCESS(
            f"Starting Teklora Autonomous Pipeline "
            f"(limit={limit}, auto_publish={auto_publish}, threshold={threshold})..."
        ))

        result = Supervisor().dispatch("newsroom", {
            'limit': limit,
            'auto_publish': auto_publish,
            'priority_threshold': threshold,
        })

        if result.abstained:
            self.stdout.write(self.style.WARNING(f"[--] {result.notes}."))
            return

        articles = result.output
        self.stdout.write(self.style.SUCCESS(
            f"[OK] Cycle complete. {len(articles)} articles generated."
        ))
        for a in articles:
            self.stdout.write(f" - [{a.status.upper()}] #{a.id}: {a.title}")
