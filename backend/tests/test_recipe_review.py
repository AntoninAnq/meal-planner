"""Deciding whether a household's recipe becomes everyone's.

Two gates, and they are not the same one: **sharing** is a person deciding that
this text may leave its kitchen, **verification** is derived from the
ingredients and decides whether a household with an allergy may be served it.
A recipe can be shared and unverified, and the pre-filter sorts that out.

What must not happen is a refusal costing somebody their own dinner: rejecting
leaves the recipe exactly where it was, usable, with a reason its author can
read.

SQLite, like the other router suites: CI runs without Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    Household,
    Operator,
    Recipe,
    RecipeIngredient,
)
from app.domain.enums import OperatorLevel, RecipeSourceType
from app.routers.admin import (
    RejectRequest,
    pending_recipes,
    reject_recipe,
    share_recipe,
    unshare_recipe,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_: object, compiler: object, **kw: object) -> str:
    return "JSON"


TABLES = [
    Household.__table__,
    Recipe.__table__,
    RecipeIngredient.__table__,
    Operator.__table__,
]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine)()


@pytest.fixture
def operator() -> Operator:
    return Operator(auth_subject="google:1", level=OperatorLevel.OWNER)


def _written(db: Session, title: str = "Steak purée", *, lines: tuple[str, ...] = ()) -> Recipe:
    household = Household(name="Mon foyer")
    db.add(household)
    db.flush()
    recipe = Recipe(
        title=title,
        source_type=RecipeSourceType.USER,
        household_id=household.id,
        instructions="Cuire le steak, écraser les pommes de terre.",
        submitted_at=datetime.now(UTC),
    )
    db.add(recipe)
    db.flush()
    for position, raw in enumerate(lines):
        db.add(
            RecipeIngredient(recipe_id=recipe.id, position=position, raw_text=raw)
        )
    db.commit()
    return recipe


def test_the_queue_shows_what_it_takes_to_judge(db: Session, operator: Operator) -> None:
    """The method above all: it is what tells a dish somebody cooks from a page
    copied off a site."""
    _written(db, lines=("1 steak", "3 pommes de terre"))

    pending = pending_recipes(db, operator)

    assert len(pending) == 1
    assert pending[0].instructions is not None
    assert pending[0].lines == ["1 steak", "3 pommes de terre"]


def test_a_collected_recipe_is_never_in_the_queue(db: Session, operator: Operator) -> None:
    db.add(
        Recipe(
            title="Porc au colombo",
            source_type=RecipeSourceType.SCRAPED,
            source_url=f"https://example.invalid/{uuid.uuid4()}",
        )
    )
    db.commit()

    assert pending_recipes(db, operator) == []


def test_sharing_takes_it_out_of_the_queue(db: Session, operator: Operator) -> None:
    recipe = _written(db)

    share_recipe(recipe.id, db, operator)

    assert db.get(Recipe, recipe.id).shared_at is not None  # type: ignore[union-attr]
    assert pending_recipes(db, operator) == []


def test_sharing_does_not_touch_verification(db: Session, operator: Operator) -> None:
    """Two gates. An unverified recipe is shared like any other and simply
    never reaches a household with an allergy (I3)."""
    recipe = _written(db)

    share_recipe(recipe.id, db, operator)

    assert db.get(Recipe, recipe.id).allergens_verified is False  # type: ignore[union-attr]


def test_rejecting_leaves_the_recipe_with_its_household(
    db: Session, operator: Operator
) -> None:
    recipe = _written(db)
    household_id = recipe.household_id

    reject_recipe(recipe.id, RejectRequest(reason="copied"), db, operator)

    kept = db.get(Recipe, recipe.id)
    assert kept is not None
    assert kept.household_id == household_id
    assert (kept.rejected_reason, kept.shared_at) == ("copied", None)
    assert pending_recipes(db, operator) == []


def test_a_reason_outside_the_list_is_refused(db: Session, operator: Operator) -> None:
    """The author reads it, so an operator's own words would arrive as a
    verdict on the person."""
    with pytest.raises(ValueError):
        RejectRequest(reason="mauvais goût")


def test_un_sharing_gives_it_back_rather_than_killing_it(
    db: Session, operator: Operator
) -> None:
    """Different from `withdraw`, which marks a recipe dead for everyone
    including the household that wrote it."""
    recipe = _written(db)
    share_recipe(recipe.id, db, operator)

    unshare_recipe(recipe.id, db, operator)

    kept = db.get(Recipe, recipe.id)
    assert kept is not None
    assert (kept.shared_at, kept.deprecated_at) == (None, None)
    assert kept.household_id is not None


def test_a_recipe_belonging_to_nobody_cannot_be_shared(
    db: Session, operator: Operator
) -> None:
    collected = Recipe(
        title="Porc au colombo",
        source_type=RecipeSourceType.SCRAPED,
        source_url=f"https://example.invalid/{uuid.uuid4()}",
    )
    db.add(collected)
    db.commit()

    with pytest.raises(HTTPException) as refused:
        share_recipe(collected.id, db, operator)

    assert refused.value.status_code == 404
