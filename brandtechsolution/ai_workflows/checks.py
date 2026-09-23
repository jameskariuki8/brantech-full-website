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


@register()
def check_env_file_drift(app_configs, **kwargs):
    """Report a credential the repo-root .env sets differently from what loaded.

    This project has two .env files describing two environments, and only one
    of them is ever read by a given process -- `brandtechsolution/.env` under a
    local `manage.py`, the repo-root one under docker-compose. Editing the
    wrong one is silent: both files are valid, and the process reads its own
    correctly while ignoring the change entirely.

    A warning rather than an error, and only for credentials. The two files are
    *supposed* to disagree about database hosts and DEBUG; they are not
    supposed to disagree about an API key, because a key is an account fact
    rather than an environment one. See `config.SHARED_CREDENTIALS`.

    Fingerprints, never values: enough to tell two keys apart in a terminal,
    useless to anyone who reads it out of a log.
    """
    try:
        from brandtechsolution.config import ROOT_ENV_FILE, credential_drift

        drifted = credential_drift()
    except Exception:  # noqa: BLE001 - a broken check must not stop startup
        return []

    if not drifted:
        return []

    detail = ", ".join(
        f"{key} (loaded {live}, file says {stated})"
        for key, live, stated in drifted
    )
    return [Warning(
        f"{ROOT_ENV_FILE} disagrees with the credentials actually loaded: {detail}.",
        hint=(
            "This process reads brandtechsolution/.env; docker-compose reads "
            "the repo-root one. Update whichever the process you are running "
            "actually loads -- the fingerprints say which is which."
        ),
        id="ai_workflows.W002",
    )]
