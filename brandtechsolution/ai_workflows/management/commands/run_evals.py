"""Run the agent eval suite.

    manage.py run_evals                      # every case, once each
    manage.py run_evals --baseline           # mark as the reference run
    manage.py run_evals --agent fact_verifier
    manage.py run_evals --samples 5          # measure the spread too
    manage.py run_evals --compare            # against the latest baseline
    manage.py run_evals --live               # include cases that call a real model
"""
from django.core.management.base import BaseCommand, CommandError

from ai_workflows.harness.evals.runner import EvalRunner, compare
from ai_workflows.models import EvalRun


class Command(BaseCommand):
    help = "Run the agent evals and record the scores."

    def add_arguments(self, parser):
        parser.add_argument('--agent', action='append', dest='agents',
                            help="Limit to this agent; repeatable.")
        parser.add_argument('--case', action='append', dest='cases',
                            help="Limit to this case by name; repeatable.")
        parser.add_argument('--samples', type=int, default=1,
                            help="Runs per case. Above 1 also reports the spread.")
        parser.add_argument('--label', default='',
                            help="What is being measured, e.g. 'native-structured-output'.")
        parser.add_argument('--baseline', action='store_true',
                            help="Mark this run as the reference others compare against.")
        parser.add_argument('--compare', action='store_true',
                            help="Report the delta against the most recent baseline.")
        parser.add_argument('--live', action='store_true',
                            help=("Include cases that call a real model. These cost "
                                  "money and need a working provider, so they are "
                                  "off by default."))

    def handle(self, *args, **options):
        runner = EvalRunner(
            samples=options['samples'],
            label=options['label'],
            is_baseline=options['baseline'],
            live=options['live'],
        )

        if options['live']:
            self.stdout.write(self.style.WARNING(
                "  Live cases are included: this run will call a real provider "
                "and cost money."
            ))

        try:
            run = runner.run(agents=options['agents'], cases=options['cases'])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self._report(run)

        if options['compare']:
            baseline = (
                EvalRun.objects.filter(is_baseline=True, status='complete')
                .exclude(pk=run.pk).first()
            )
            if baseline is None:
                self.stdout.write(self.style.WARNING(
                    "\nNo baseline run recorded yet; nothing to compare against. "
                    "Capture one with --baseline."
                ))
            else:
                self._report_comparison(run, baseline)

        # A failing case has to fail the command, or the suite becomes
        # decoration that nobody notices going red.
        failed = run.results.filter(passed=False).count()
        unmeasured = run.results.filter(passed__isnull=True).count()

        problems = []
        if failed:
            problems.append(f"{failed} check(s) failed")
        if unmeasured:
            # Also an error. A run where half the cases could not execute --
            # a quota limit, a dead provider -- once reported "overall: 1.00"
            # and exited zero, which is an eval suite lying about the one thing
            # it exists to tell the truth about.
            problems.append(f"{unmeasured} check(s) could not be measured")

        if problems:
            raise CommandError(" and ".join(problems) + ".")

    def _report(self, run):
        self.stdout.write(f"\nEval run #{run.pk}  {run.label or '(unlabelled)'}"
                          f"  samples={run.samples_per_case}")
        self.stdout.write("=" * 64)

        for agent in run.agents:
            results = [r for r in run.results.all() if r.agent == agent]
            score = run.score_for(agent)
            shown = "n/a" if score is None else f"{score:.2f}"
            self.stdout.write(f"\n  {agent}  ({shown})")

            for result in results:
                if result.passed is True:
                    mark, style = "PASS", self.style.SUCCESS
                elif result.passed is False:
                    mark, style = "FAIL", self.style.ERROR
                else:
                    mark, style = "  ? ", self.style.WARNING
                suffix = f" -- {result.detail}" if result.detail else ""
                self.stdout.write(style(
                    f"    {mark}  {result.case} [{result.grader}]{suffix}"
                ))

        overall = run.score
        total = run.results.count()
        unmeasured = run.results.filter(passed__isnull=True).count()
        graded = total - unmeasured

        self.stdout.write("\n" + "=" * 64)
        # The count is of what was actually *graded*. Reporting a score over
        # "9 checks" when four of them raised reads as a complete run that went
        # well, which is the opposite of what happened.
        line = (f"  overall: {'n/a' if overall is None else f'{overall:.2f}'}"
                f"   ({graded} of {total} checks graded)")
        self.stdout.write(line if not unmeasured else self.style.WARNING(line))

        if unmeasured:
            self.stdout.write(self.style.ERROR(
                f"  {unmeasured} check(s) could not be measured at all. "
                f"The score above covers only the rest of them."
            ))

    def _report_comparison(self, run, baseline):
        self.stdout.write(f"\nvs baseline #{baseline.pk} "
                          f"({baseline.label or 'unlabelled'})")
        self.stdout.write("-" * 64)
        for agent, row in compare(run, baseline).items():
            if row['delta'] is None:
                self.stdout.write(f"  {agent}: not comparable "
                                  f"(score={row['score']}, baseline={row['baseline']})")
                continue
            arrow = "=" if row['delta'] == 0 else ("+" if row['delta'] > 0 else "")
            style = (self.style.SUCCESS if row['delta'] > 0
                     else self.style.ERROR if row['delta'] < 0
                     else self.style.NOTICE)
            self.stdout.write(style(
                f"  {agent}: {row['baseline']:.2f} -> {row['score']:.2f} "
                f"({arrow}{row['delta']:.2f})"
            ))
