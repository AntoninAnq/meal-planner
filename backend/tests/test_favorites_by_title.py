"""A favourite with no recipe, kept by its title.

"Pâtes au jambon" has no page in the catalogue and no ingredients. What is
pinned here is what that costs and what it does not: it can be saved, twice is
still once, it stays offered in a slot, and in a household with an allergy it
says that nothing was checked — while a household with only an aversion is not
asked anything.

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
from app.domain.enums import AllergenCode, ConstraintSeverity, LifeStage
from app.routers.favorites import add_favorite, list_favorites, remove_favorite_by_title
from app.schemas import FavoriteCreate


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


def _constraint(db: Session, household_id: uuid.UUID, severity: ConstraintSeverity) -> None:
    member = Member(household_id=household_id, display_name="Léa", life_stage=LifeStage.TEEN_ADULT)
    db.add(member)
    db.flush()
    db.add(
        DietaryConstraint(
            household_id=household_id,
            member_id=member.id,
            allergen_code=AllergenCode.GLUTEN,
            severity=severity,
        )
    )
    db.commit()


def test_a_dish_without_a_recipe_is_kept_as_written(db: Session, household: uuid.UUID) -> None:
    favorite = add_favorite(FavoriteCreate(label="  Pâtes au jambon "), db, household)

    assert favorite.recipe_id is None
    assert favorite.title == "Pâtes au jambon"
    assert favorite.minutes is None
    assert favorite.source_url is None


def test_the_same_title_twice_is_one_favourite(db: Session, household: uuid.UUID) -> None:
    add_favorite(FavoriteCreate(label="Pâtes au jambon"), db, household)
    add_favorite(FavoriteCreate(label="Pâtes au jambon"), db, household)

    assert len(db.scalars(select(HouseholdFavorite)).all()) == 1


def test_neither_or_both_is_refused(db: Session, household: uuid.UUID) -> None:
    for payload in (
        FavoriteCreate(),
        FavoriteCreate(label="   "),
        FavoriteCreate(recipe_id=uuid.uuid4(), label="Pâtes au jambon"),
    ):
        with pytest.raises(HTTPException) as refused:
            add_favorite(payload, db, household)
        assert refused.value.status_code == 422


def test_a_title_is_always_offered_in_a_slot(db: Session, household: uuid.UUID) -> None:
    """No source to withdraw and no dish type: the slot filter has nothing to
    hold against it."""
    add_favorite(FavoriteCreate(label="Pâtes au jambon"), db, household)

    assert [row.title for row in list_favorites(db, household, for_slot=True)] == [
        "Pâtes au jambon"
    ]


def test_nothing_is_said_about_allergens_where_nobody_has_one(
    db: Session, household: uuid.UUID
) -> None:
    add_favorite(FavoriteCreate(label="Pâtes au jambon"), db, household)

    assert list_favorites(db, household)[0].unchecked_allergens is False


def test_an_allergy_in_the_household_makes_it_ask_first(db: Session, household: uuid.UUID) -> None:
    _constraint(db, household, ConstraintSeverity.SEVERE_ALLERGY)

    favorite = add_favorite(FavoriteCreate(label="Pâtes au jambon"), db, household)

    assert favorite.unchecked_allergens is True
    assert favorite.conflicts == []


def test_an_aversion_asks_nothing(db: Session, household: uuid.UUID) -> None:
    """Red is reserved: "n'aime pas" is not a reason to stop someone."""
    _constraint(db, household, ConstraintSeverity.AVERSION)

    favorite = add_favorite(FavoriteCreate(label="Pâtes au jambon"), db, household)

    assert favorite.unchecked_allergens is False


def test_removing_by_title(db: Session, household: uuid.UUID) -> None:
    add_favorite(FavoriteCreate(label="Pâtes au jambon"), db, household)

    remove_favorite_by_title(" Pâtes au jambon", db, household)

    assert list_favorites(db, household) == []
