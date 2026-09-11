"""The favourites contract, at the three points where it can quietly go wrong.

The CRUD is thin. What is worth pinning down is what the schema does for us and
what it does not: that a second POST is not an error, that a withdrawn recipe
stops being offered as a replacement without vanishing from the tab, and that
the allergen warning names both the allergen and the person — while an aversion
never raises it, because red is reserved.

SQLite, like the quota and revocation suites: CI runs without Postgres.
`Recipe.source_categories` is JSONB, which has no SQLite equivalent, so it is
compiled down to JSON for this suite only — the alternative is not testing the
join at all.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    DietaryConstraint,
    Household,
    HouseholdFavorite,
    Member,
    Recipe,
    RecipeAllergen,
)
from app.domain.enums import (
    AllergenCode,
    ConstraintSeverity,
    DishType,
    LifeStage,
    RecipeSourceType,
)
from app.routers.favorites import add_favorite, list_favorites, remove_favorite
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


def _recipe(
    db: Session,
    title: str = "Porc au colombo",
    *,
    dish_type: DishType | None = DishType.MAIN,
    deprecated: bool = False,
    prep: int | None = 15,
    cook: int | None = 40,
) -> uuid.UUID:
    from datetime import UTC, datetime

    recipe = Recipe(
        title=title,
        source_type=RecipeSourceType.SCRAPED,
        source_url=f"https://example.invalid/{uuid.uuid4()}",
        dish_type=dish_type,
        prep_minutes=prep,
        cook_minutes=cook,
        complexity=2,
        deprecated_at=datetime.now(UTC) if deprecated else None,
    )
    db.add(recipe)
    db.commit()
    return recipe.id


def _allergic(
    db: Session,
    household_id: uuid.UUID,
    name: str,
    allergen: AllergenCode,
    severity: ConstraintSeverity = ConstraintSeverity.SEVERE_ALLERGY,
) -> None:
    member = Member(household_id=household_id, display_name=name, life_stage=LifeStage.TEEN_ADULT)
    db.add(member)
    db.flush()
    db.add(
        DietaryConstraint(
            household_id=household_id,
            member_id=member.id,
            allergen_code=allergen,
            severity=severity,
        )
    )
    db.commit()


# -- Adding, twice -----------------------------------------------------------


def test_a_favourite_carries_the_declared_effort(db: Session, household: uuid.UUID) -> None:
    recipe_id = _recipe(db)

    favorite = add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    assert favorite.recipe_id == recipe_id
    assert favorite.title == "Porc au colombo"
    assert favorite.minutes == 55
    assert favorite.complexity == 2


def test_a_recipe_declaring_no_time_says_nothing(db: Session, household: uuid.UUID) -> None:
    """Null rather than zero: a card that shows "0 min" implies a recipe is
    instant, which is the invented metadata the V0 refusal was about."""
    recipe_id = _recipe(db, prep=None, cook=None)

    assert add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household).minutes is None


def test_adding_the_same_recipe_twice_is_not_an_error(
    db: Session, household: uuid.UUID
) -> None:
    """A two-state button means a second POST is a click that arrived twice."""
    recipe_id = _recipe(db)

    add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)
    again = add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    assert again.recipe_id == recipe_id
    assert len(db.scalars(select(HouseholdFavorite)).all()) == 1


def test_two_households_keep_their_own_lists(db: Session, household: uuid.UUID) -> None:
    other = Household(name="Autre foyer")
    db.add(other)
    db.commit()
    recipe_id = _recipe(db)

    add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    assert list_favorites(db, other.id) == []


# -- Removing ----------------------------------------------------------------


def test_removing_something_absent_is_not_an_error(db: Session, household: uuid.UUID) -> None:
    """The row is already gone from the screen; a 404 would make an optimistic
    update look like a failure."""
    remove_favorite(_recipe(db), db, household)

    assert list_favorites(db, household) == []


def test_removing_takes_it_out_of_the_list(db: Session, household: uuid.UUID) -> None:
    recipe_id = _recipe(db)
    add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    remove_favorite(recipe_id, db, household)

    assert list_favorites(db, household) == []


# -- What may still be served ------------------------------------------------


def test_a_withdrawn_recipe_leaves_the_slot_but_stays_on_the_tab(
    db: Session, household: uuid.UUID
) -> None:
    """Two different questions. The tab asks what the household saved — and it
    can still remove it there. The slot asks what may be cooked tonight."""
    withdrawn = _recipe(db, "Source morte", deprecated=True)
    add_favorite(FavoriteCreate(recipe_id=withdrawn), db, household)

    assert [row.recipe_id for row in list_favorites(db, household)] == [withdrawn]
    assert list_favorites(db, household, for_slot=True) == []


def test_a_dessert_is_not_offered_as_a_replacement(
    db: Session, household: uuid.UUID
) -> None:
    dessert = _recipe(db, "Tarte au citron", dish_type=DishType.DESSERT)
    add_favorite(FavoriteCreate(recipe_id=dessert), db, household)

    assert list_favorites(db, household, for_slot=True) == []


def test_an_unclassified_recipe_passes_like_it_does_in_the_prefilter(
    db: Session, household: uuid.UUID
) -> None:
    """111 of 555 verified recipes carry no `dish_type`. Refusing them here
    would hide a fifth of the catalogue behind a rule about desserts."""
    unclassified = _recipe(db, "Rien de déclaré", dish_type=None)
    add_favorite(FavoriteCreate(recipe_id=unclassified), db, household)

    assert [row.recipe_id for row in list_favorites(db, household, for_slot=True)] == [
        unclassified
    ]


# -- The allergen, and who it belongs to -------------------------------------


def test_a_conflict_names_the_allergen_and_the_person(
    db: Session, household: uuid.UUID
) -> None:
    """"This dish contains an allergen" alone sends the reader off to check
    who — and both halves are one join away."""
    recipe_id = _recipe(db)
    db.add(RecipeAllergen(recipe_id=recipe_id, allergen_code=AllergenCode.GLUTEN))
    db.commit()
    _allergic(db, household, "Joséphine", AllergenCode.GLUTEN)
    add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    [favorite] = list_favorites(db, household, for_slot=True)

    assert [(c.allergen_code, c.member_name) for c in favorite.conflicts] == [
        (AllergenCode.GLUTEN, "Joséphine")
    ]


def test_an_aversion_never_raises_the_allergen_warning(
    db: Session, household: uuid.UUID
) -> None:
    """Red is what this product keeps for the allergen and for the
    irreversible. Spending it on "n'aime pas" spends it everywhere."""
    recipe_id = _recipe(db)
    db.add(RecipeAllergen(recipe_id=recipe_id, allergen_code=AllergenCode.MILK))
    db.commit()
    _allergic(db, household, "Flora", AllergenCode.MILK, ConstraintSeverity.AVERSION)
    add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    [favorite] = list_favorites(db, household, for_slot=True)

    assert favorite.conflicts == []


def test_an_allergen_nobody_here_carries_is_not_a_conflict(
    db: Session, household: uuid.UUID
) -> None:
    recipe_id = _recipe(db)
    db.add(RecipeAllergen(recipe_id=recipe_id, allergen_code=AllergenCode.PEANUTS))
    db.commit()
    _allergic(db, household, "Joséphine", AllergenCode.GLUTEN)
    add_favorite(FavoriteCreate(recipe_id=recipe_id), db, household)

    [favorite] = list_favorites(db, household, for_slot=True)

    assert favorite.conflicts == []
