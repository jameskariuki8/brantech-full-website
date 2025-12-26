from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import os

# BASE_DIR points to brandtechsolution directory (where .env file is located)
BASE_DIR = Path(__file__).resolve().parent.parent

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env")

    # Gemini API Configuration
    google_api_key: str
    chroma_persist_directory: str = "./chroma_db"
    
    # Gemini Model Configuration
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "models/embedding-001"
    
    # LangSmith Configuration (optional)
    langsmith_tracing: bool = True
    langsmith_api_key: str
    langsmith_project: str = "brantech-ai"

    # Database Configuration (defaults for Postgres)
    database_engine: str = "postgresql"
    database_name: str = "brantech"
    database_user: str
    database_password: str
    database_host: str = "localhost"
    database_port: str = "5432"
    database_conn_max_age: int = 60

config = AppSettings()