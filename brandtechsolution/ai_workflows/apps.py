from django.apps import AppConfig


class AiWorkflowsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_workflows'

    def ready(self):
        # Registers the provider system check. Imported here rather than at
        # module scope so it happens once the app registry is populated.
        from ai_workflows import checks  # noqa: F401

        # Connects the save hooks that keep site content searchable.
        # `harness/indexing.py` shipped in step 2 describing exactly this and
        # was never wired to anything, so every vector was as stale as the
        # last time somebody ran a management command by hand.
        from ai_workflows import signals  # noqa: F401
