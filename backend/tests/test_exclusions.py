"""Withholding a dish, and the one rule it shares with the favourite.

What the pool does with a withheld recipe is pinned in the pre-filter suite
(`withhold`). What is pinned here is the contract the panel relies on: a second
click is not an error, restoring something absent is not an error, and a recipe
is never a favourite and withheld at once — the latest answer holds.

SQLite, like the favourites suite: CI runs without Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    DietaryConstraint,
    Household,
    HouseholdExclusion,
    HouseholdFavorite,
    Member,
    Recipe,
    RecipeAllergen,
)
from app.domain.enums import RecipeSourceType
from app.routers.exclusions import add_exclusion, list_exclusions, remove_exclusion
from app.routers.favorites import add_favorite, list_favorites
from app.schemas import ExclusionCreate, FavoriteCreate


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_: object, compiler: object, **kw: object) -> str:
    return "JSON"


TABLES = [
    Household.__table__,
    Member.__table__,
    Recipe.__table__,
    RecipeAllergen.__table__,
    DietaryConstraint.__table__,
    HouseholdFavorite.__table__,
    HouseholdExclusion.__table__,
]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine)()


@pytest.fixture
def household(db: Session) -> uuid.UUID:
    row = Household(name="Mon foyer")
    db.add(row)
    db.commit()
    return row.id


def _recipe(db: Session, title: str = "Porc au colombo") -> uuid.UUID:
    recipe = Recipe(
        title=title,
        source_type=RecipeSourceType.SCRAPED,
        source_url=f"https://example.invalid/{uuid.uuid4()}",
    )
    db.add(recipe)
    db.commit()
    return recipe.id


def test_withholding_twice_is_not_an_error(db: Session, household: uuid.UUID) -> None:
    recipe_id = _recipe(db)

    add_exclusion(ExclusionCreate(recipe_id=recipe_id), db, household)
    again = add_exclusion(ExclusionCreate(recipe_id=recipe_id), db, household)

    assert again.title == "Porc au colombo"
    assert len(db.scalars(select(HouseholdExclusion)).all()) == 1


def test_withholding_an_unknown_recipe_is_a_404(db: Session, household: uuid.UUID) -> None:
    with pytest.raises(HTTPException) as refused:
        add_exclusion(ExclusionCreate(recipe_id=uuid.uuid4()), db, household)

    assert refused.value.status_code == 404


def test_restoring_something_absent_is_not_an_error(db: Session, household: uuid.UUID) -> None:
    remove_exclusion(_recipe(db), db, household)

    assert list_exclusions(db, household) == []


def test_restoring_takes_it_off_the_list(db: Session, household: uuid.UUID) -> None:
    recipe_id = _recipe(db)
    add_exclusion(ExclusionCreate(recipe_id=recipe_id), db, household)

    remove_exclusion(recipe_id, db, household)

    assert list_exclusions(db, household) == []


def test_two_households_keep_their_own_lists(db: Session, household: uuid.UUID) -> None:
    other = Household(name="Autre foyer")
    db.add(other)
    db.commit()

    add_exclusion(ExclusionCreate(recipe_id=_recipe(db)), db, household)

    assert list_exclusions(db, other.id) == []


def test_withholding_a_favourite_takes_it_off_the_favourites(
    db: Session, household: uuid.UUID
) -> None:
    """"Reproposez-le-moi" and "plus jamais" cannot both hold."""
    recipe_id = _recipe(db)
    add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    add_exclusion(ExclusionCreate(recipe_id=recipe_id), db, household)

    assert list_favorites(db, household) == []
    assert [row.recipe_id for row in list_exclusions(db, household)] == [recipe_id]


def test_favouriting_a_withheld_dish_brings_it_back(db: Session, household: uuid.UUID) -> None:
    recipe_id = _recipe(db)
    add_exclusion(ExclusionCreate(recipe_id=recipe_id), db, household)

    add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    assert list_exclusions(db, household) == []
    assert [row.recipe_id for row in list_favorites(db, household)] == [recipe_id]
