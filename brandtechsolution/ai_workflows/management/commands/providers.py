"""List the providers, and choose which model each one serves.

Step 3 built the catalogue and step 10 wired it to `get_model`, which makes
one question operational: *which* of a provider's models do we actually send
requests to. The harness refuses to guess -- a heuristic pick out of five
hundred models produces answers that look exactly like the right ones at a
price nobody chose -- so the choice has to be made, and this is where.

    manage.py providers
    manage.py providers --set openai=gpt-5
    manage.py providers --models openai --grep gpt
"""
from django.core.management.base import BaseCommand, CommandError

from ai_workflows.harness.catalogue import (
    can_serve,
    chosen_model,
    model_is_serviceable,
)


class Command(BaseCommand):
    help = "Show providers and their chosen chat model; set one with --set."

    def add_arguments(self, parser):
        parser.add_argument(
            "--set", metavar="PROVIDER=MODEL_ID", action="append", default=[],
            help="Choose the model a provider serves. Repeatable.",
        )
        parser.add_argument(
            "--models", metavar="PROVIDER",
            help="List a provider's available models instead.",
        )
        parser.add_argument(
            "--grep", metavar="TEXT", default="",
            help="With --models, show only ids containing TEXT.",
        )

    def handle(self, *args, **options):
        if options["set"]:
            for assignment in options["set"]:
                self._set(assignment)
            self.stdout.write("")

        if options["models"]:
            return self._models(options["models"], options["grep"])

        return self._list()

    # ------------------------------------------------------------------

    def _set(self, assignment):
        from ai_workflows.models import CatalogueEntry, Provider

        if "=" not in assignment:
            raise CommandError(f"expected PROVIDER=MODEL_ID, got {assignment!r}")

        name, model_id = (part.strip() for part in assignment.split("=", 1))
        provider = Provider.objects.filter(name=name).first()
        if provider is None:
            known = ", ".join(Provider.objects.values_list("name", flat=True)) or "none"
            raise CommandError(f"no provider named {name!r} (known: {known})")

        # Checked against the catalogue, but not enforced: the catalogue may
        # not have been refreshed since the model shipped, and refusing a valid
        # id because our copy of the listing is stale would be worse than
        # saying so.
        if model_id and not CatalogueEntry.objects.filter(
            provider=name, model_id=model_id, available=True,
        ).exists():
            self.stdout.write(self.style.WARNING(
                f"  note: {model_id!r} is not in the catalogue for {name}. "
                f"Setting it anyway; run refresh_catalogue if that is a surprise."
            ))

        provider.default_model = model_id
        provider.save(update_fields=["default_model"])
        self.stdout.write(self.style.SUCCESS(
            f"  {name} -> {model_id or '(cleared)'}"
        ))

    def _models(self, name, grep):
        from ai_workflows.models import CatalogueEntry

        rows = CatalogueEntry.objects.filter(provider=name, available=True)
        if grep:
            rows = rows.filter(model_id__icontains=grep)
        rows = rows.order_by("model_id")

        if not rows:
            self.stdout.write(self.style.WARNING(
                f"  No catalogued models for {name}"
                + (f" matching {grep!r}" if grep else "")
                + ". Run refresh_catalogue."
            ))
            return

        self.stdout.write("")
        for entry in rows:
            price = (
                f"${entry.input_price_per_mtok:g}/${entry.output_price_per_mtok or 0:g}"
                if entry.input_price_per_mtok is not None else "price unknown"
            )
            context = f"{entry.context_tokens:,}" if entry.context_tokens else "?"
            self.stdout.write(f"  {entry.model_id:<45} {context:>10} ctx  {price}")
        self.stdout.write(f"\n  {len(rows)} model(s)\n")

    def _list(self):
        from ai_workflows.models import Provider

        providers = list(Provider.objects.order_by("preference", "name"))
        if not providers:
            self.stdout.write(self.style.WARNING(
                "\n  No providers recorded yet. Run refresh_catalogue.\n"
            ))
            return

        self.stdout.write("")
        usable = 0

        for provider in providers:
            model = chosen_model(provider.name)
            has_key = can_serve(provider.name)
            ready = (
                provider.usable and has_key and bool(model)
                and model_is_serviceable(provider.name, model)
            )
            usable += bool(ready)

            # `has_key` before `status`, because OpenRouter verifies without
            # one -- its listing is public -- and would otherwise be reported
            # ready while being unable to answer a single request.
            mark, style = (
                ("ready   ", self.style.SUCCESS) if ready else
                ("no key  ", self.style.WARNING) if not has_key else
                ("no model", self.style.WARNING) if not model else
                ("retired ", self.style.ERROR) if not model_is_serviceable(provider.name, model) else
                ("unusable", self.style.ERROR)
            )

            note = ""
            if not provider.enabled:
                note = "  (disabled)"
            elif provider.status == Provider.CANDIDATE and provider.last_error:
                note = f"  {provider.last_error[:60]}"

            self.stdout.write(
                f"  {style(mark)}  {provider.name:<12} pref={provider.preference:<4} "
                f"{model or '-'}{note}"
            )

        self.stdout.write("")
        summary = f"  {usable} of {len(providers)} provider(s) can serve a request"
        self.stdout.write(
            summary if usable else self.style.ERROR(summary + " -- nothing will run")
        )
        self.stdout.write("")
