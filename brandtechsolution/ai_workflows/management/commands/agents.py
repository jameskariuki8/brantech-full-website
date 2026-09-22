"""List the agents and how each one is doing.

Step 5 made agent health recordable and step 8 made the agents enumerable;
this is the two of them joined up. Until now the only way to know whether the
newsroom was working was to open the dashboard and see whether anything new
had appeared, which cannot distinguish "nothing happened" from "everything
failed".
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from ai_workflows.harness.supervisor import ROUTES, Supervisor

MARKS = {
    "healthy": "ok     ",
    "failing": "FAILING",
    "unknown": "unknown",
}


class Command(BaseCommand):
    help = "List the registered agents, their routes, and their health."

    def add_arguments(self, parser):
        parser.add_argument(
            "--failing", action="store_true",
            help="Show only agents currently failing.",
        )

    def handle(self, *args, **options):
        supervisor = Supervisor()
        report = supervisor.status()

        routes = {}
        for task, agent in ROUTES.items():
            routes.setdefault(agent, []).append(task)

        rows = sorted(report.items())
        if options["failing"]:
            rows = [(name, row) for name, row in rows if row["status"] == "failing"]
            if not rows:
                self.stdout.write(self.style.SUCCESS("No agent is currently failing."))
                return

        width = max((len(name) for name, _ in rows), default=10)
        self.stdout.write("")

        for name, row in rows:
            mark = MARKS.get(row["status"], row["status"])
            style = {
                "failing": self.style.ERROR,
                "healthy": self.style.SUCCESS,
            }.get(row["status"], self.style.WARNING)

            line = f"  {style(mark)}  {name:<{width}}  {', '.join(sorted(routes.get(name, [])))}"
            self.stdout.write(line)

            if row["status"] == "failing":
                since = row["failing_since"]
                elapsed = timezone.now() - since if since else None
                detail = f"           {row['error_class']}"
                if elapsed is not None:
                    detail += f", failing for {_duration(elapsed)}"
                if row["suppressed"]:
                    detail += f", {row['suppressed']} further failure(s) suppressed"
                self.stdout.write(self.style.ERROR(detail))

        self.stdout.write("")
        failing = sum(1 for _, row in rows if row["status"] == "failing")
        unknown = sum(1 for _, row in rows if row["status"] == "unknown")
        summary = f"  {len(rows)} agents, {failing} failing, {unknown} never run"
        self.stdout.write(self.style.ERROR(summary) if failing else summary)
        self.stdout.write("")


def _duration(delta):
    """A rough human duration. Exactness is not the point here."""
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"
