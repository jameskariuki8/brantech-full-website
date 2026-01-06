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
    )

    # ============================================================
    # Django Core Settings
    # ============================================================
    secret_key: str
    debug: bool = True
    allowed_hosts: list[str] = ["teklora.co.ke", "www.teklora.co.ke", "127.0.0.1", "localhost"]

    # ============================================================
    # Email Configuration
    # ============================================================
    email_host: str = "smtp.gmail.com"
    email_port: int = 587
    email_use_tls: bool = True
    email_host_user: str = ""
    email_host_password: str = ""

    # ============================================================
    # Gemini API Configuration
    # ============================================================
    google_api_key: str
    
    # Gemini Model Configuration
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "models/embedding-001"
    
    # ============================================================
    # LangSmith Configuration
    # ============================================================
    langsmith_tracing: str = "true"
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "brantech-ai"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

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


# Create global config instance
config = AppSettings()