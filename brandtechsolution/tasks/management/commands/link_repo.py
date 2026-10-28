from django.core.management.base import BaseCommand, CommandError

from tasks.github import poll_repository
from tasks.models import Repository
from tasks.serializers import RepositorySerializer


class Command(BaseCommand):
    help = "Link a GitHub repository to the task board. Use --check to sync immediately."

    def add_arguments(self, parser):
        parser.add_argument("repository", help="owner/name or GitHub URL")
        parser.add_argument("--no-roadmap", action="store_true", help="Only track commits")
        parser.add_argument("--check", action="store_true", help="Read GitHub now (may create and assign tasks)")

    def handle(self, *args, **options):
        # Reuse API normalization and validation, including duplicate detection.
        validator = RepositorySerializer()
        raw = options["repository"].strip()
        from rest_framework.exceptions import ValidationError
        try:
            name = validator.validate_full_name(raw)
        except ValidationError:
            import re
            name = re.sub(r"^(?:https?://)?(?:www\.)?github\.com/", "", raw, flags=re.I).removesuffix(".git").strip("/")
            if not Repository.objects.filter(full_name__iexact=name).exists():
                raise CommandError("Use owner/name or the repository's GitHub link.")
        repository = Repository.objects.filter(full_name__iexact=name).first()
        if repository is None:
            repository = Repository.objects.create(full_name=name, track_roadmap=not options["no_roadmap"])
        elif options["no_roadmap"]:
            repository.track_roadmap = False
            repository.save(update_fields=["track_roadmap"])
        self.stdout.write(self.style.SUCCESS(f"Linked {repository.full_name}"))
        if options["check"]:
            try:
                result = poll_repository(repository)
            except Exception as exc:
                Repository.objects.filter(pk=repository.pk).update(last_error=str(exc)[:1000])
                raise CommandError(f"GitHub sync failed: {exc}") from exc
            self.stdout.write(str(result))
