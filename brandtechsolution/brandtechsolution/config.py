"""
Central configuration management for the application.

All environment variables should be loaded through this module.
The .env file should be located in the brandtechsolution/ directory.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional

# BASE_DIR points to brandtechsolution directory (where .env file is located)
BASE_DIR = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All environment variables are loaded from:
    1. .env file in brandtechsolution/ directory
    2. System environment variables (takes precedence)
    """
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Ignore env vars / .env keys that aren't declared here (e.g. tooling
        # secrets like GITHUB_ACCESS_TOKEN) so a shared .env doesn't crash startup.
        extra="ignore",
    )

    # ============================================================
    # Django Core Settings
    # ============================================================
    secret_key: str
    debug: bool = True
    allowed_hosts: list[str] = ["teklora.co.ke", "www.teklora.co.ke", "127.0.0.1", "localhost"]
    # HTTPS origins trusted for CSRF (required behind the Cloudflare Tunnel where
    # TLS terminates at the edge). Must include the scheme.
    csrf_trusted_origins: list[str] = ["https://teklora.co.ke", "https://www.teklora.co.ke"]

    # ============================================================
    # Email Configuration
    # ============================================================
    email_host: str = "smtp.gmail.com"
    email_port: int = 587
    email_use_tls: bool = True
    email_host_user: str = ""
    email_host_password: str = ""
    email_timeout: int = 10

    # ============================================================
    # Bulk mail outbox
    # ============================================================
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 3
    outbox_stale_claim_minutes: int = 15
    site_base_url: str = "https://teklora.co.ke"

    # ============================================================
    # Cloudflare Turnstile (bot protection on public forms)
    # ============================================================
    # Both come from the Cloudflare dashboard under Turnstile. The site key is
    # public and rendered into the page; the secret key is not and is only
    # ever sent server-to-server to siteverify.
    #
    # Leaving them empty disables the checks, which is what you want on a
    # developer machine. A Django system check refuses to start with DEBUG
    # off and no secret, so an unprotected deployment cannot happen quietly -
    # see brandtechsolution/turnstile.py.
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""

    # ============================================================
    # Public contact form rate limiting
    # ============================================================
    contact_rate_limit_count: int = 5
    contact_rate_limit_window_seconds: int = 3600

    # ============================================================
    # Gemini API Configuration
    # ============================================================
    google_api_key: str
    
    # Gemini Model Configuration
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "models/gemini-embedding-001"
    
    # ============================================================
    # LangSmith Configuration
    # ============================================================
    langsmith_tracing: str = "true"
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "brantech-ai"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # ============================================================
    # GitHub Integration Configuration
    # ============================================================
    github_access_token: Optional[str] = None
    github_username: Optional[str] = None

    # ============================================================
    # Database Configuration
    # ============================================================
    database_engine: str = "postgresql"
    database_name: str = "brantech"
    database_user: str
    database_password: str
    database_host: str = "localhost"
    database_port: str = "5432"
    database_conn_max_age: int = 60

    # ============================================================
    # Static & Media (filesystem paths)
    # ============================================================
    static_root: str = str(BASE_DIR / "staticfiles")
    media_root: str = str(BASE_DIR / "media")


# Create global config instance
config = AppSettings()