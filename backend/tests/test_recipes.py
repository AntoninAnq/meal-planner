"""A household writing its own recipe.

"Steak purée" is a legitimate answer to "what are we eating", and the catalogue
has nothing like it. What is pinned here is what that costs and what it does
not: a title alone is enough, the lines are read by the same parser as the
catalogue's, verification stays derived (I3) rather than declared, the recipe
belongs to its household and to nobody else, and editing a shared one puts it
back in the queue instead of changing everyone's week silently.

SQLite, like the other router suites: CI runs without Postgres. The check
constraint on `instructions` is Postgres's and is exercised by the migration,
not here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

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
    Ingredient,
    IngredientAlias,
    IngredientAllergen,
    MealPlan,
    Member,
    PlannedDish,
    Recipe,
    RecipeAllergen,
    RecipeIngredient,
)
from app.domain.enums import AllergenCode, DishSource, MealType
from app.routers.favorites import list_favorites
from app.routers.recipes import (
    create_recipe,
    delete_recipe,
    list_recipes,
    search_ingredients,
    update_recipe,
)
from app.schemas import RecipeIn


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_: object, compiler: object, **kw: object) -> str:
    return "JSON"


TABLES = [
    Household.__table__,
    # Listing the favourites names the allergen AND the person it belongs to.
    Member.__table__,
    DietaryConstraint.__table__,
    Ingredient.__table__,
    IngredientAlias.__table__,
    IngredientAllergen.__table__,
    Recipe.__table__,
    RecipeIngredient.__table__,
    RecipeAllergen.__table__,
    HouseholdFavorite.__table__,
    HouseholdExclusion.__table__,
    MealPlan.__table__,
    PlannedDish.__table__,
]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    for table in TABLES:
        for column in table.columns:
            if column.server_default is not None and "::jsonb" in str(column.server_default.arg):
                column.server_default = None
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine)()


@pytest.fixture
def household(db: Session) -> uuid.UUID:
    row = Household(name="Mon foyer")
    db.add(row)
    db.commit()
    return row.id


def _food(
    db: Session,
    name: str,
    *,
    confirmed: bool = True,
    allergen: AllergenCode | None = None,
) -> uuid.UUID:
    """One entry of the referential. Unconfirmed ones are proposals: they
    resolve, and they do not make a recipe verified (I3)."""
    ingredient = Ingredient(
        canonical_name=name.capitalize(),
        normalized_name=name,
        confirmed_at=datetime.now(UTC) if confirmed else None,
    )
    db.add(ingredient)
    db.flush()
    if allergen is not None:
        db.add(IngredientAllergen(ingredient_id=ingredient.id, allergen_code=allergen))
    db.commit()
    return ingredient.id


def test_a_title_alone_is_enough(db: Session, household: uuid.UUID) -> None:
    """A form that demands quantities before it accepts "steak purée" is a form
    nobody fills in."""
    recipe = create_recipe(RecipeIn(title="  Steak purée  "), db, household)

    assert recipe.title == "Steak purée"
    assert recipe.lines == []
    assert recipe.allergens_verified is False
    assert recipe.state == "pending"


def test_a_new_recipe_is_a_favourite_straight_away(db: Session, household: uuid.UUID) -> None:
    """Writing one IS saying "I want this again"."""
    recipe = create_recipe(RecipeIn(title="Steak purée"), db, household)

    assert [row.recipe_id for row in list_favorites(db, household)] == [recipe.id]


def test_the_lines_are_read_like_the_catalogue_s(db: Session, household: uuid.UUID) -> None:
    _food(db, "tomate")

    recipe = create_recipe(
        RecipeIn(title="Salade", lines=["400 g de tomates", "Pour la sauce :"]),
        db,
        household,
    )

    food, heading = recipe.lines
    assert (food.quantity, food.unit, food.name) == (400, "g", "Tomate")
    assert heading.is_structural is True
    assert heading.ingredient_id is None


def test_every_line_recognised_makes_it_verified(db: Session, household: uuid.UUID) -> None:
    _food(db, "tomate")
    _food(db, "riz")

    recipe = create_recipe(
        RecipeIn(title="Riz aux tomates", lines=["400 g de tomates", "200 g de riz"]),
        db,
        household,
    )

    assert recipe.allergens_verified is True


def test_one_line_nobody_knows_leaves_it_unverified(db: Session, household: uuid.UUID) -> None:
    """It stays perfectly usable — its author knows what they wrote — but it is
    never proposed on its own, and the line lands in "non reconnues"."""
    _food(db, "tomate")

    recipe = create_recipe(
        RecipeIn(title="Salade", lines=["400 g de tomates", "3 gombos"]),
        db,
        household,
    )

    assert recipe.allergens_verified is False
    assert [line.ingredient_id is None for line in recipe.lines] == [False, True]


def test_a_proposed_food_does_not_vouch_for_anything(db: Session, household: uuid.UUID) -> None:
    """I3 read literally: a referential entry nobody confirmed is a proposal,
    and a machine-written referential must not become a safety guarantee."""
    _food(db, "tomate", confirmed=False)

    recipe = create_recipe(RecipeIn(title="Salade", lines=["400 g de tomates"]), db, household)

    assert recipe.lines[0].ingredient_id is not None
    assert recipe.allergens_verified is False


def test_the_allergens_of_its_foods_are_derived(db: Session, household: uuid.UUID) -> None:
    _food(db, "lait", allergen=AllergenCode.MILK)

    recipe = create_recipe(RecipeIn(title="Béchamel", lines=["50 cl de lait"]), db, household)

    codes = db.scalars(
        select(RecipeAllergen.allergen_code).where(RecipeAllergen.recipe_id == recipe.id)
    ).all()
    assert codes == [AllergenCode.MILK]


def test_the_servings_are_written_as_people(db: Session, household: uuid.UUID) -> None:
    """The form asked for people, so the shopping list can scale it — which is
    the reason the field is on the form at all."""
    recipe = create_recipe(RecipeIn(title="Steak purée", servings=4), db, household)

    assert (recipe.servings, recipe.servings_raw) == (4, "4 personnes")


def test_another_household_cannot_read_it(db: Session, household: uuid.UUID) -> None:
    other = Household(name="Autre foyer")
    db.add(other)
    db.commit()
    recipe = create_recipe(RecipeIn(title="Steak purée"), db, household)

    assert list_recipes(db, other.id) == []
    with pytest.raises(HTTPException) as refused:
        update_recipe(recipe.id, RecipeIn(title="Volé"), db, other.id)
    assert refused.value.status_code == 404


def test_editing_a_shared_recipe_puts_it_back_in_the_queue(
    db: Session, household: uuid.UUID
) -> None:
    """Otherwise the review is decorative: validated bland, rewritten after."""
    recipe = create_recipe(RecipeIn(title="Steak purée"), db, household)
    db.get(Recipe, recipe.id).shared_at = datetime.now(UTC)  # type: ignore[union-attr]
    db.commit()

    edited = update_recipe(recipe.id, RecipeIn(title="Steak purée maison"), db, household)

    assert edited.state == "pending"
    assert db.get(Recipe, recipe.id).shared_at is None  # type: ignore[union-attr]


def test_a_recipe_on_a_planned_week_is_not_deleted(db: Session, household: uuid.UUID) -> None:
    """The week records what was eaten; the database would refuse anyway."""
    recipe = create_recipe(RecipeIn(title="Steak purée"), db, household)
    plan = MealPlan(household_id=household, week_start=date(2026, 9, 7))
    db.add(plan)
    db.flush()
    db.add(
        PlannedDish(
            meal_plan_id=plan.id,
            day_of_week=0,
            meal_type=MealType.DINNER,
            recipe_id=recipe.id,
            source=DishSource.USER,
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as refused:
        delete_recipe(recipe.id, db, household)

    assert refused.value.status_code == 409


def test_deleting_takes_it_out_of_the_favourites(db: Session, household: uuid.UUID) -> None:
    recipe = create_recipe(RecipeIn(title="Steak purée"), db, household)

    delete_recipe(recipe.id, db, household)

    assert list_recipes(db, household) == []
    assert list_favorites(db, household) == []


def test_the_search_helps_name_a_line_nobody_recognised(
    db: Session, household: uuid.UUID
) -> None:
    _food(db, "huile d'olive")
    _food(db, "olive noire")

    found = [match.name for match in search_ingredients(db, household, "olive")]

    # Prefix first, then the rest: that is how someone types a word they know.
    assert found == ["Olive noire", "Huile d'olive"]
