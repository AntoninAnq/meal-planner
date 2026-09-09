"""Configurations that boot, answer, and are quietly wrong.

Every case below describes an instance that starts and serves without a single
error message: people sign in, weeks generate, nothing on any page says the
deployment is unsafe. That is why they are refused at startup rather than
warned about — a warning in a log nobody is reading yet is the same as nothing.

The pair that matters most is `APP_BASE_URL` / `ENVIRONMENT`: `cookie_secure`
reads the second, so an HTTPS deployment that forgot `ENVIRONMENT=prod` issues
its session cookie without `Secure`. A checklist cannot catch that, because the
checklist was followed and one line of it was not.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import MINIMUM_SECRET_LENGTH, Settings

STRONG = "x" * MINIMUM_SECRET_LENGTH
PROD = {
    "environment": "prod",
    "app_base_url": "https://repas.example.org",
    "session_secret": STRONG,
    "google_client_id": "id",
    "google_client_secret": "secret",
    "llm_provider": "anthropic",
    "anthropic_api_key": "sk-ant-…",
}


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test about a configuration must not read the machine's own.

    Without this these tests pass or fail depending on what happens to be
    exported around them: they were green only because the development
    container sets `LLM_PROVIDER=ollama`, and the same file failed on a runner
    that does not. Every field is cleared, and `_env_file=None` below drops the
    developer's `.env` too, so what each case asserts is exactly what it passes
    in.
    """
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**PROD, **overrides})  # type: ignore[arg-type]


def settings_without(*omitted: str, **overrides: object) -> Settings:
    """A field left OUT, which is not the same as a field set to nothing.

    `LLM_PROVIDER=` unset is the case under test; passing `None` would only
    prove that `None` is not a valid provider.
    """
    given = {key: value for key, value in PROD.items() if key not in omitted}
    return Settings(_env_file=None, **{**given, **overrides})  # type: ignore[arg-type]


def test_a_complete_production_configuration_is_accepted() -> None:
    assert settings().cookie_secure is True


def test_local_development_needs_none_of_it() -> None:
    # http://localhost, no Google credentials, a throwaway secret: the whole
    # point is that the guardrails do not make the project harder to run.
    local = Settings(_env_file=None, session_secret="dev")  # type: ignore[call-arg]
    assert local.environment == "dev"
    assert local.cookie_secure is False


def test_https_without_prod_is_refused() -> None:
    # The silent one. It boots, it works, and the session cookie travels
    # without Secure for as long as nobody thinks to look.
    with pytest.raises(ValidationError, match="Secure"):
        settings(environment="dev")


def test_prod_without_https_is_refused() -> None:
    with pytest.raises(ValidationError, match="APP_BASE_URL"):
        settings(app_base_url="http://repas.example.org")


def test_a_short_secret_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        settings(session_secret="changeme")


def test_a_secret_exactly_at_the_floor_passes() -> None:
    assert settings(session_secret="a" * MINIMUM_SECRET_LENGTH)


@pytest.mark.parametrize(
    "missing", ["google_client_id", "google_client_secret"]
)
def test_missing_google_credentials_are_refused_in_production(missing: str) -> None:
    # Otherwise the instance starts and fails for the first visitor who clicks
    # the only button on the page.
    with pytest.raises(ValidationError, match="missing in prod"):
        settings(**{missing: ""})


def test_an_unset_provider_is_refused_in_production() -> None:
    # `fake` answers `{}` — valid JSON, an empty proposal — so the instance
    # serves empty weeks full of violations and looks like a broken model.
    with pytest.raises(ValidationError, match="LLM_PROVIDER is unset"):
        settings_without("llm_provider", "anthropic_api_key")


def test_fake_stays_allowed_when_it_is_written_down() -> None:
    # Deploying once without a key, to check that signing in works before
    # paying for anything, is a reasonable thing to want.
    assert settings(llm_provider="fake").llm_provider == "fake"


def test_anthropic_without_a_key_is_refused_at_boot() -> None:
    # The factory raises on this too, but only for the first visitor asking for
    # a week — as a 500.
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        settings(anthropic_api_key="")
