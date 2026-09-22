"""What the agents have cost.

`run_evals` answers whether the output is any good and `agents` answers whether
anything is broken. Neither could answer what any of it cost, because until
`harness/usage.py` nothing recorded it.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count, Q, Sum
from django.utils import timezone


class Command(BaseCommand):
    help = "Report recorded model spend, by agent, provider or model."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=float, default=7,
            help="How far back to look. 0 means everything ever recorded.",
        )
        parser.add_argument(
            "--by", choices=["agent", "provider", "model", "label"], default="agent",
            help="What to group the report by.",
        )
        parser.add_argument("--agent", default="", help="Only this agent.")
        parser.add_argument("--run", type=int, default=None, help="Only this run id.")
        parser.add_argument(
            "--limit", type=int, default=20, help="Rows to show.",
        )

    def handle(self, *args, **options):
        from ai_workflows.models import ModelInvocation

        rows = ModelInvocation.objects.all()

        window = ""
        if options["days"]:
            since = timezone.now() - timedelta(days=options["days"])
            rows = rows.filter(created_at__gte=since)
            window = f" in the last {options['days']:g} day(s)"
        if options["agent"]:
            rows = rows.filter(agent=options["agent"])
        if options["run"] is not None:
            rows = rows.filter(run_id=options["run"])

        if not rows.exists():
            self.stdout.write(f"No model calls recorded{window}.")
            return

        field = {
            "agent": "agent", "provider": "provider",
            "model": "model_id", "label": "label",
        }[options["by"]]

        grouped = (
            rows.values(field)
            .annotate(
                calls=Count("id"),
                prompt=Sum("prompt_tokens"),
                completion=Sum("completion_tokens"),
                reasoning=Sum("reasoning_tokens"),
                spend=Sum("cost_usd"),
                unpriced=Count("id", filter=Q(cost_usd__isnull=True)),
            )
            .order_by("-spend", "-calls")[: options["limit"]]
        )

        self.stdout.write(f"\nModel spend by {options['by']}{window}\n")
        self.stdout.write(
            f"{options['by']:<24} {'calls':>7} {'in':>10} {'out':>10} "
            f"{'(reason)':>10} {'USD':>12}"
        )
        self.stdout.write("-" * 78)

        for row in grouped:
            name = row[field] or "(unattributed)"
            spend = row["spend"]
            # An unpriced call is not a free one. Marking the total rather than
            # printing a confident number is the whole point of carrying
            # `price_source` through from the catalogue.
            shown = f"${spend:.4f}" if spend is not None else "unpriced"
            if row["unpriced"]:
                shown += f" +{row['unpriced']}?"
            self.stdout.write(
                f"{name[:24]:<24} {row['calls']:>7} {row['prompt'] or 0:>10,} "
                f"{row['completion'] or 0:>10,} {row['reasoning'] or 0:>10,} "
                f"{shown:>12}"
            )

        self._totals(rows, window)

    def _totals(self, rows, window):
        figures = rows.aggregate(
            calls=Count("id"),
            tokens=Sum("total_tokens"),
            spend=Sum("cost_usd"),
            unpriced=Count("id", filter=Q(cost_usd__isnull=True)),
        )
        self.stdout.write("-" * 78)
        total = figures["spend"]
        line = (
            f"{figures['calls']} calls, {figures['tokens'] or 0:,} tokens, "
            f"${total or 0:.4f}"
        )
        self.stdout.write(self.style.SUCCESS(line))

        if figures["unpriced"]:
            self.stdout.write(self.style.WARNING(
                f"{figures['unpriced']} of those calls used a model with no "
                f"known price, so the real total is higher than ${total or 0:.4f}. "
                f"Run `manage.py refresh_catalogue` or add the price to "
                f"harness/pricing.toml."
            ))

        borrowed = rows.filter(price_source="openrouter").count()
        if borrowed:
            self.stdout.write(
                f"note: {borrowed} call(s) priced from OpenRouter's listing, "
                f"which is what OpenRouter charges to proxy the model rather "
                f"than what the provider charges directly."
            )
