"""Startup reporting for the model providers.

Same precedent as brandtechsolution/mailgun.py's check_email_configured and
turnstile.py: a deployment should not have to guess whether its credentials
took. Those two refuse to start when misconfigured; this one only reports,
because a provider being absent is a normal state -- Gemini alone is a working
deployment -- and the one thing that *is* fatal is having no usable provider
at all.
"""
from django.core.checks import Error, Warning, register


@register()
def check_providers(app_configs, **kwargs):
    """Report which providers have credentials, and refuse to run with none."""
    from django.conf import settings

    # The check runs at startup, including during migrate on a fresh database
    # where these tables do not exist yet.
    try:
        from ai_workflows.harness.providers import ADAPTERS
    except Exception:  # noqa: BLE001
        return []

    configured = [name for name, adapter in ADAPTERS.items() if adapter.has_credential()]

    if configured:
        return []

    if settings.DEBUG or getattr(settings, "TESTING", False):
        return [Warning(
            "No model provider credential is configured; agent calls will fail.",
            hint="Set GOOGLE_API_KEY, or another provider's key.",
            id="ai_workflows.W001",
        )]

    return [Error(
        "No model provider credential is configured with DEBUG off. Every "
        "agent call will fail.",
        hint="Set GOOGLE_API_KEY, or another provider's key.",
        id="ai_workflows.E001",
    )]
