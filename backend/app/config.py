"""Application configuration.

Invariant I8: no technical dependency is hardcoded. Every outside-world address,
credential and tunable lives here and comes from the environment.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["ollama", "anthropic", "fake"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["dev", "prod"] = "dev"

    # Public entry point. Also the base for the OAuth redirect URI.
    app_base_url: str = "http://localhost:8080"

    # The connection is assembled HERE, from the parts, rather than handed over
    # as a ready-made URL by Compose. Two independent reasons, both learned the
    # hard way:
    #
    #   * A password is a byte string; a URL is a parsed grammar. `%` starts an
    #     escape, `@` ends the userinfo, `/` ends the authority. Quoting it is
    #     this layer's job, and it is done below.
    #   * Compose INTERPOLATION mangles values containing YAML indicator
    #     characters — `!`, `%`, `&`, `*`. A password made of exactly those came
    #     through `${...}` altered, while the same variable delivered by
    #     `env_file` arrived byte-exact. So the secret never travels through an
    #     interpolated field: it reaches the process untouched, as
    #     POSTGRES_PASSWORD, and the URL is built after that.
    #
    # DATABASE_URL is still honoured when set, for a hosted database that hands
    # out one connection string and no parts.
    database_url: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_db: str = ""
    postgres_host: str = "db"
    postgres_port: int = 5432

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
    #: The context window, in tokens. Written here because Ollama's own default
    #: is 4 096 while `qwen3:8b` declares 40 960 — so leaving it unset uses a
    #: tenth of the model, chosen by nobody (I8).
    #:
    #: It is a RESERVATION, not a limit reached progressively: the KV cache is
    #: allocated in full when the model loads. On this model — 36 layers, 8
    #: key/value heads of dimension 128 — one token costs 144 KiB, so 8 192
    #: reserves 1.13 GiB on top of the ~4.9 GiB of weights. Widening it costs
    #: memory, never latency; what costs latency is FILLING it.
    #:
    #: 8 192 leaves room for roughly 190 candidate lines at 31 tokens each,
    #: which is well beyond the 60-120 the pre-filter sends.
    ollama_context_tokens: int = 8192
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
    #: The ingredient referential, mounted from `db/` in the repository. It is
    #: versioned and reviewed as a Git diff — see db/README.md for why that
    #: matters on the data the allergen filter rests on.
    catalog_referential_path: str = "/db/ingredients.yaml"
    #: Human approvals of that referential. A separate file because
    #: `ingredients.yaml` is hand-annotated and this one is machine-written —
    #: and versioned, because the confirmations are the one part of the
    #: pipeline no machine can reproduce.
    catalog_confirmations_path: str = "/db/confirmations.yaml"
    #: Source rubric -> moment of the meal. Versioned next to the referential
    #: and reviewed the same way, but it carries no allergen, so it never goes
    #: through `catalog review` — I1 has nothing to say about it.
    catalog_dish_types_path: str = "/db/dish_types.yaml"
    catalog_cache_dir: str = "/var/cache/catalog"
    catalog_cache_ttl_seconds: float = 24 * 3600
    catalog_request_timeout_seconds: float = 30.0

    @property
    def sqlalchemy_url(self) -> str:
        """`DATABASE_URL` if one was given, otherwise built from the parts."""
        if self.database_url:
            return self.database_url
        if not (self.postgres_user and self.postgres_db):
            raise RuntimeError(
                "no database configured: set DATABASE_URL, or POSTGRES_USER / "
                "POSTGRES_PASSWORD / POSTGRES_DB"
            )
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password, safe="")
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

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
