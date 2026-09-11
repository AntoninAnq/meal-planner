"""Replacing a dish: what must follow it out, and what must stay behind.

The write itself is one column. What is worth pinning down is the wake: a
serving variant describes ONE preparation, so it cannot survive the dish it was
written for — and neither can the confirmation attached to it. §4.9 puts the
baby's plate on the parent, and a confirmation that outlives the plate it was
given for turns that into a signature on a blank page.

The two provenance flags are set on every replace rather than only when true,
so neither lingers from an earlier one.

SQLite, like the other router suites: CI runs without Postgres. The plan's JSONB
columns are compiled down to JSON for this suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    DietaryConstraint,
    Household,
    Ingredient,
    MealPlan,
    Member,
    PlannedDish,
    PlannedDishMember,
    PlannedDishMemberRemoval,
    Recipe,
    RecipeAllergen,
    RecipeIngredient,
    RecipeSuitableStage,
)
from app.domain.enums import (
    AllergenCode,
    ConstraintSeverity,
    DishSource,
    LifeStage,
    MealType,
    RecipeSourceType,
)
from app.routers.meal_plans import replace_dish
from app.schemas import DishReplace


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_: object, compiler: object, **kw: object) -> str:
    return "JSON"


TABLES = [
    Household.__table__,
    Ingredient.__table__,
    Member.__table__,
    Recipe.__table__,
    RecipeIngredient.__table__,
    RecipeAllergen.__table__,
    RecipeSuitableStage.__table__,
    DietaryConstraint.__table__,
    MealPlan.__table__,
    PlannedDish.__table__,
    PlannedDishMember.__table__,
    PlannedDishMemberRemoval.__table__,
]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    # `'[]'::jsonb` is a Postgres cast and SQLite cannot parse the DDL at all.
    # Dropped for this engine only: the defaults matter to the database, and
    # every row this suite writes sets those columns from Python anyway.
    for table in TABLES:
        for column in table.columns:
            if column.server_default is not None and "::jsonb" in str(
                column.server_default.arg
            ):
                column.server_default = None
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine)()


def _recipe(db: Session, title: str) -> uuid.UUID:
    recipe = Recipe(
        title=title,
        source_type=RecipeSourceType.SCRAPED,
        source_url=f"https://example.invalid/{uuid.uuid4()}",
    )
    db.add(recipe)
    db.commit()
    return recipe.id


@pytest.fixture
def plan(db: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A Thursday dinner with a baby on a serving variant, already confirmed."""
    household = Household(name="Mon foyer")
    db.add(household)
    db.flush()
    baby = Member(
        household_id=household.id, display_name="Marceau", life_stage=LifeStage.BABY
    )
    db.add(baby)
    db.flush()

    meal_plan = MealPlan(household_id=household.id, week_start=date(2026, 9, 7))
    db.add(meal_plan)
    db.flush()

    dish = PlannedDish(
        meal_plan_id=meal_plan.id,
        day_of_week=3,
        meal_type=MealType.DINNER,
        recipe_id=_recipe(db, "Moussaka à la viande"),
        source=DishSource.CATALOG,
    )
    db.add(dish)
    db.flush()
    db.add(
        PlannedDishMember(
            planned_dish_id=dish.id,
            member_id=baby.id,
            serving_variant="part prélevée avant salage et mixée",
            variant_confirmed_at=datetime.now(UTC),
        )
    )
    db.commit()
    return household.id, meal_plan.id, dish.id, baby.id


def _assignment(db: Session, dish_id: uuid.UUID) -> PlannedDishMember:
    found = db.query(PlannedDishMember).filter_by(planned_dish_id=dish_id).one()
    return found


# -- What must not survive the dish ------------------------------------------


def test_the_serving_variant_leaves_with_the_dish_it_described(
    db: Session, plan: tuple[uuid.UUID, ...]
) -> None:
    """"Part prélevée avant salage" is an instruction about one preparation.
    Pinned on a recipe nobody wrote it for, it is worse than nothing."""
    household_id, plan_id, dish_id, _ = plan

    replace_dish(plan_id, dish_id, DishReplace(recipe_id=_recipe(db, "Colombo")), db, household_id)

    assert _assignment(db, dish_id).serving_variant is None


def test_the_confirmation_leaves_with_the_variant(
    db: Session, plan: tuple[uuid.UUID, ...]
) -> None:
    """A parent confirmed THIS texture for THIS child on THAT dish. Carrying
    the confirmation over to a dish they never saw is the system deciding
    again under someone's name — exactly what §4.9 exists to prevent."""
    household_id, plan_id, dish_id, _ = plan

    replace_dish(plan_id, dish_id, DishReplace(recipe_id=_recipe(db, "Colombo")), db, household_id)

    assert _assignment(db, dish_id).variant_confirmed_at is None


def test_the_eater_stays(db: Session, plan: tuple[uuid.UUID, ...]) -> None:
    """The variant goes, the person does not: Marceau is still eating on
    Thursday, and it is his portion that now needs recomputing."""
    household_id, plan_id, dish_id, baby_id = plan

    replace_dish(plan_id, dish_id, DishReplace(recipe_id=_recipe(db, "Colombo")), db, household_id)

    assert _assignment(db, dish_id).member_id == baby_id


# -- The two flags -----------------------------------------------------------


def test_a_favourite_marks_the_dish_as_placed(
    db: Session, plan: tuple[uuid.UUID, ...]
) -> None:
    household_id, plan_id, dish_id, _ = plan

    replace_dish(
        plan_id,
        dish_id,
        DishReplace(recipe_id=_recipe(db, "Colombo"), from_favorite=True),
        db,
        household_id,
    )

    assert db.get(PlannedDish, dish_id).placed_from_favorite is True


def test_choosing_a_suggestion_afterwards_clears_the_flag(
    db: Session, plan: tuple[uuid.UUID, ...]
) -> None:
    """Otherwise "depuis vos favoris" stays on screen over a dish that came
    from the suggestions."""
    household_id, plan_id, dish_id, _ = plan
    replace_dish(
        plan_id,
        dish_id,
        DishReplace(recipe_id=_recipe(db, "Colombo"), from_favorite=True),
        db,
        household_id,
    )

    replace_dish(
        plan_id, dish_id, DishReplace(recipe_id=_recipe(db, "Gratin")), db, household_id
    )

    assert db.get(PlannedDish, dish_id).placed_from_favorite is False


def test_an_accepted_allergen_is_recorded_and_then_dropped(
    db: Session, plan: tuple[uuid.UUID, ...]
) -> None:
    """It must survive the click — and only for the dish it was about."""
    household_id, plan_id, dish_id, _ = plan
    risky = _recipe(db, "Tarte")
    db.add(RecipeAllergen(recipe_id=risky, allergen_code=AllergenCode.GLUTEN))
    # An allergy always belongs to somebody: `ck_dietary_constraint_member_required`
    # only lets an aversion float free of a member, and its household scope comes
    # from its severity rather than from its storage.
    eater = Member(
        household_id=household_id, display_name="Joséphine", life_stage=LifeStage.TEEN_ADULT
    )
    db.add(eater)
    db.flush()
    db.add(
        DietaryConstraint(
            household_id=household_id,
            member_id=eater.id,
            allergen_code=AllergenCode.GLUTEN,
            severity=ConstraintSeverity.SEVERE_ALLERGY,
        )
    )
    db.commit()

    replace_dish(
        plan_id,
        dish_id,
        DishReplace(recipe_id=risky, from_favorite=True, allergen_override=True),
        db,
        household_id,
    )
    assert db.get(PlannedDish, dish_id).allergen_override is True

    replace_dish(
        plan_id, dish_id, DishReplace(recipe_id=_recipe(db, "Gratin")), db, household_id
    )
    assert db.get(PlannedDish, dish_id).allergen_override is False


def test_a_hand_written_title_is_neither(db: Session, plan: tuple[uuid.UUID, ...]) -> None:
    household_id, plan_id, dish_id, _ = plan

    replace_dish(plan_id, dish_id, DishReplace(label="Restes de dimanche"), db, household_id)

    dish = db.get(PlannedDish, dish_id)
    assert (dish.placed_from_favorite, dish.allergen_override) == (False, False)
