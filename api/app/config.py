"""Application configuration.

Invariant I8: no technical dependency is hardcoded. Every outside-world address,
credential and tunable lives here and comes from the environment.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["ollama", "anthropic", "fake"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["dev", "prod"] = "dev"

    # Public entry point. Also the base for the OAuth redirect URI.
    app_base_url: str = "http://localhost:8080"

    database_url: str

    # Session cookie
    session_secret: str
    session_cookie_name: str = "mp_session"
    session_max_age_seconds: int = 30 * 24 * 3600

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # LLM
    llm_provider: LLMProvider = "fake"
    llm_max_attempts: int = 3
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3:8b"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/api/auth/callback"

    @property
    def cookie_secure(self) -> bool:
        """Never send the session cookie over plain HTTP outside local dev."""
        return self.environment == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
