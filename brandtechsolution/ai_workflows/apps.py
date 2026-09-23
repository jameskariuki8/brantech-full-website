from django.apps import AppConfig


class AiWorkflowsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_workflows'

    def ready(self):
        # Registers the provider system check. Imported here rather than at
        # module scope so it happens once the app registry is populated.
        from ai_workflows import checks  # noqa: F401
