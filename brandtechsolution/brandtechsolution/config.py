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

    # Mailgun is the preferred transport; the SMTP settings above are only a
    # fallback for a deployment that has not been given Mailgun credentials.
    # base_url is the API root and must not include the domain -- EU accounts
    # use https://api.eu.mailgun.net/v3.
    mailgun_api_key: str = ""
    mailgun_base_url: str = "https://api.mailgun.net/v3"
    mailgun_domain: str = ""

    # The public From address. Defaults to noreply@<mailgun_domain>, because a
    # From address outside the sending domain fails SPF and DKIM alignment and
    # lands the mail in spam.
    default_from_email: str = ""

    # Where "an article is waiting for review" lands. Falls back to
    # email_host_user, which is what this used before the move to Mailgun.
    editorial_review_email: str = ""

    # ============================================================
    # Bulk mail outbox
    # ============================================================
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 3
    outbox_stale_claim_minutes: int = 15
    site_base_url: str = "https://teklora.co.ke"

    # ============================================================
    # Redis / Celery
    # ============================================================
    # One Redis instance backs three things: the Celery broker (db 0), the
    # Celery result backend (db 1) and the Django cache (db 2). Separate
    # logical databases so that clearing the cache can never drop queued work.
    #
    # In docker compose the host is the `redis` service; on a developer
    # machine it defaults to localhost, and if no Redis is running the cache
    # falls back to locmem (see settings.py) so runserver still works.
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    # Set to True on a developer machine without a worker: tasks then execute
    # inline in the calling process instead of being queued. The test suite
    # forces this on regardless, so tests never need a live broker.
    celery_task_always_eager: bool = False

    # Hard ceilings for a single task. The editorial pipeline makes eight
    # sequential Gemini calls and routinely runs three minutes, so these are
    # deliberately generous; the soft limit fires first and raises
    # SoftTimeLimitExceeded, which the tasks catch to record a failure.
    celery_task_soft_time_limit: int = 900
    celery_task_time_limit: int = 1200
    celery_worker_concurrency: int = 2

    # Beat intervals, in seconds.
    beat_outbox_interval: int = 60
    beat_github_sync_interval: int = 3600

    @property
    def redis_url_base(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}"

    @property
    def celery_broker_url(self) -> str:
        return f"{self.redis_url_base}/0"

    @property
    def celery_result_backend(self) -> str:
        return f"{self.redis_url_base}/1"

    @property
    def django_cache_url(self) -> str:
        return f"{self.redis_url_base}/2"

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

    # Likes are one request each and a reader may work through a page of
    # posts, so this is far looser than the contact form -- it exists to stop
    # a script inflating the "popular" ranking, not to pace a human.
    blog_like_rate_limit_count: int = 30
    blog_like_rate_limit_window_seconds: int = 60

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