"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Secrets come from env / .env — never hardcode them."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Software Evolution Platform"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api"

    cors_origins: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173",
        description="Comma-separated allowed CORS origins",
    )
    frontend_url: str = "http://127.0.0.1:5173"

    mongodb_uri: str = "mongodb://127.0.0.1:27017"
    mongodb_db: str = "ai_software_evolution"

    session_secret: str = "change-me-to-a-long-random-secret"
    session_cookie_name: str = "ase_session"
    session_expire_minutes: int = 10080
    cookie_secure: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/api/auth/google/callback"

    chroma_persist_dir: str = ""  # empty => %TEMP%/ase_chroma (avoids OneDrive locks)

    gemini_api_key: str = ""
    # Architecture generation (Phase 3)
    gemini_model: str = "gemini-3.5-flash"
    gemini_architecture_fallback_model: str = "gemini-3.1-flash-lite"
    # Repository RAG chat (Phase 4) — same API key, separate models
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_chat_fallback_model: str = "gemini-3.1-flash-lite"

    embedding_model_name: str = "all-MiniLM-L6-v2"

    repo_clone_dir: str = ""  # empty => %TEMP%/ase_repos (avoids OneDrive file locks)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id.strip() and self.google_client_secret.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
