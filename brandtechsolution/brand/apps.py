from django.apps import AppConfig


class BrandConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'brand'

    def ready(self):
        # Importing the module is what registers its @register() system
        # check. Without this the "Turnstile is unconfigured in production"
        # guard never runs, which is the one thing it exists to prevent.
        from brandtechsolution import turnstile  # noqa: F401

        # Same reason: registers the "email would go to stdout in production"
        # check, which is the guard against a campaign reporting every
        # recipient sent while nothing left the building.
        from brandtechsolution import mailgun  # noqa: F401
