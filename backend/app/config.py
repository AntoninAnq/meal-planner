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
    #: A whole week on a local 8B is minutes, not seconds, and the prompt grows
    #: as the household does. Written in the code it would be a technical value
    #: in the wrong place (I8) — and the failure it causes reads as "the model
    #: is unreachable", which sends you looking in entirely the wrong place.
    ollama_timeout_seconds: float = 600.0
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"

    # Catalogue
    #: Path to the whitelist. It is deliberately NOT part of the source tree.
    #:
    #: Two reasons, and the second is the one that matters. First, I8: the same
    #: pipeline must be able to run against a different list of sources without
    #: a commit. Second, this repository is public, and the list names sites
    #: whose authors were never asked. The mechanism and the collection policy
    #: are published and auditable in full; who is fetched is deployment
    #: configuration and stays out.
    #:
    #: `backend/sources.example.yaml` is the template to copy.
    catalog_sources_path: str = "/config/sources.yaml"
    #: Campaign cache. A named Docker volume, so it never reaches the repository
    #: and `docker compose down -v` purges it. It exists so that re-running a
    #: campaign does not mean asking a stranger's server for the same page
    #: again — not to archive anyone's pages (I9).
    catalog_cache_dir: str = "/var/cache/catalog"
    catalog_cache_ttl_seconds: float = 24 * 3600
    catalog_request_timeout_seconds: float = 30.0

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
