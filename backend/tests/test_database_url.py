"""How the connection string is built — including the branch only prod uses.

Two paths, and each is invisible from the other environment. Development
assembles the URL from `POSTGRES_*` parts, so the `DATABASE_URL` branch that
Supabase deployments take had never been executed by anything but a person
typing it by hand. Production does the opposite, so the assembly and its
percent-encoding never run there.

The encoding is the half with teeth. `README.md` promises that special
characters are accepted in the password, `!`, `%`, `&` and `*` included — and
a password containing `@`, `/` or `:` splits a URL in the wrong place, which
surfaces as an authentication failure or a connection to a database whose name
is a fragment of the password. Nothing said that promise was tested.
"""

from __future__ import annotations

import pytest

from app.config import Settings

BASE = {"session_secret": "s", "postgres_user": "mealplanner", "postgres_db": "mealplanner"}


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """The machine's own database must not answer for the one under test."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_a_given_url_is_used_as_it_stands() -> None:
    # The production branch: Supabase hands over a ready-made string, and
    # taking it apart to reassemble it could only lose something.
    given = "postgresql+psycopg://u:p@db.supabase.co:5432/postgres"

    assert settings(database_url=given).sqlalchemy_url == given


def test_a_given_url_wins_over_the_parts() -> None:
    # Both are set on a deployment that kept its compose defaults around.
    # Silently preferring the parts would connect to a database that does not
    # exist, with an error naming a host nobody configured.
    given = "postgresql+psycopg://u:p@db.supabase.co:5432/postgres"

    assert settings(database_url=given, postgres_host="db").sqlalchemy_url == given


def test_without_a_url_it_is_assembled_from_the_parts() -> None:
    url = settings(postgres_password="secret", postgres_host="db").sqlalchemy_url

    assert url == "postgresql+psycopg://mealplanner:secret@db:5432/mealplanner"


@pytest.mark.parametrize(
    "password",
    ["p@ssword", "pass/word", "pass:word", "100%sure", "a&b*c!d", "p?w#d"],
)
def test_a_password_with_url_syntax_in_it_survives(password: str) -> None:
    """The README's promise, held to.

    `@` ends the credentials, `/` starts the database name, `:` separates user
    from password: unescaped, each one silently moves a boundary and the
    failure reads as bad credentials rather than as bad quoting.
    """
    head = "postgresql+psycopg://mealplanner:"
    tail = "@db:5432/mealplanner"
    url = settings(postgres_password=password, postgres_host="db").sqlalchemy_url

    # Whatever the escaping, the parts on either side must still be intact.
    assert url.startswith(head)
    assert url.endswith(tail)
    # And no raw delimiter may sit in the password's place.
    encoded = url[len(head) : -len(tail)]
    assert not any(delimiter in encoded for delimiter in "@/:")


def test_no_database_at_all_says_so_rather_than_guessing() -> None:
    empty = Settings(_env_file=None, session_secret="s")  # type: ignore[call-arg]

    with pytest.raises(RuntimeError, match="no database configured"):
        _ = empty.sqlalchemy_url
