"""What may be proposed, and what may only be remembered.

The predicate has two halves and the whole point of extracting it was that a
query cannot honour one and forget the other. These tests hold that: they
assert on the compiled SQL rather than on rows, because what is being checked
is that the clause is THERE — a missing filter is not a wrong answer on some
fixture, it is a dead source quietly back in next week's plan.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import Recipe
from app.services.catalogue import NOT_A_MEAL, offerable


def _sql() -> str:
    return str(select(Recipe.id).where(offerable()))


def test_it_excludes_what_is_not_a_meal() -> None:
    assert "dish_type" in _sql()
    # The rubrics themselves stay in one place; this only checks the half is on.
    assert NOT_A_MEAL


def test_it_excludes_what_has_been_withdrawn() -> None:
    assert "deprecated_at IS NULL" in _sql()


def test_a_null_rubric_still_passes() -> None:
    # 961 recipes carry no rubric anyone mapped, and excluding them would spend
    # a fifth of the catalogue on a comfort guarantee.
    assert "dish_type IS NULL" in _sql()


def test_both_halves_are_required_together() -> None:
    # AND, never OR: a withdrawn main course is still withdrawn.
    sql = _sql()
    assert " AND " in sql
    assert sql.index("dish_type") < sql.index("deprecated_at")
