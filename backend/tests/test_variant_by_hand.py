"""The parent writing — or simply accepting — the baby's portion.

Haiku writes no serving variant: 8 slots out of 8 on the first real week, 45
runs out of 45 on the bench. So the plate that needs one has nothing to
confirm, and the mark on the week had no way to come off. What is pinned here
is that confirming works without a text, that a text can be written along the
way, and that the mark follows the plates in both directions.

SQLite, like the other router suites: CI runs without Postgres.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    Household,
    MealPlan,
    Member,
    PlannedDish,
    PlannedDishMember,
    Recipe,
    RecipeSuitableStage,
)
from app.domain.enums import DishSource, LifeStage, MealType, RecipeSourceType
from app.domain.planning import STAGE_FOR_EATER
from app.routers.meal_plans import confirm_variant
from app.schemas import VariantConfirmation


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_: object, compiler: object, **kw: object) -> str:
    return "JSON"


TABLES = [
    Household.__table__,
    Member.__table__,
    Recipe.__table__,
    RecipeSuitableStage.__table__,
    MealPlan.__table__,
    PlannedDish.__table__,
    PlannedDishMember.__table__,
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


class Week:
    """A household with a baby, and one dinner the baby cannot eat as it comes."""

    def __init__(self, db: Session) -> None:
        self.db = db
        household = Household(name="Mon foyer")
        db.add(household)
        db.flush()
        self.household_id = household.id

        baby = Member(household_id=household.id, display_name="Marceau", life_stage=LifeStage.BABY)
        parent = Member(
            household_id=household.id, display_name="Flora", life_stage=LifeStage.TEEN_ADULT
        )
        db.add_all([baby, parent])
        db.flush()
        self.baby_id = baby.id

        recipe = Recipe(
            title="Porc au colombo",
            source_type=RecipeSourceType.SCRAPED,
            source_url=f"https://example.invalid/{uuid.uuid4()}",
        )
        db.add(recipe)
        db.flush()

        self.plan = MealPlan(
            household_id=household.id,
            week_start=date(2026, 9, 7),
            violations=[
                {
                    "code": STAGE_FOR_EATER,
                    "detail": "r_001 is not a meal for a baby eater",
                    "day_of_week": 0,
                    "meal_type": "dinner",
                }
            ],
        )
        db.add(self.plan)
        db.flush()

        self.dish = PlannedDish(
            meal_plan_id=self.plan.id,
            day_of_week=0,
            meal_type=MealType.DINNER,
            recipe_id=recipe.id,
            source=DishSource.CATALOG,
        )
        db.add(self.dish)
        db.flush()
        db.add_all(
            [
                PlannedDishMember(planned_dish_id=self.dish.id, member_id=baby.id),
                PlannedDishMember(planned_dish_id=self.dish.id, member_id=parent.id),
            ]
        )
        db.commit()

    def confirm(self, confirmed: bool = True, variant: str | None = None) -> None:
        confirm_variant(
            self.plan.id,
            self.dish.id,
            VariantConfirmation(member_id=self.baby_id, confirmed=confirmed, variant=variant),
            self.db,
            self.household_id,
        )

    def codes(self) -> list[str]:
        self.db.refresh(self.plan)
        return [entry["code"] for entry in self.plan.violations or []]

    def assignment(self) -> PlannedDishMember:
        return self.db.get(PlannedDishMember, (self.dish.id, self.baby_id))  # type: ignore[return-value]


def test_confirming_without_a_text_is_allowed(db: Session) -> None:
    """The model wrote nothing, so there is nothing to confirm — and the
    household still has to be able to say it dealt with the plate."""
    week = Week(db)

    week.confirm()

    assert week.assignment().variant_confirmed_at is not None
    assert week.assignment().serving_variant is None


def test_confirming_clears_the_mark_on_the_slot(db: Session) -> None:
    week = Week(db)
    assert week.codes() == [STAGE_FOR_EATER]

    week.confirm()

    assert week.codes() == []


def test_the_portion_can_be_written_along_the_way(db: Session) -> None:
    week = Week(db)

    week.confirm(variant="  part prélevée avant salage et mixée  ")

    assert week.assignment().serving_variant == "part prélevée avant salage et mixée"
    assert week.codes() == []


def test_taking_the_confirmation_back_puts_the_mark_back(db: Session) -> None:
    """A mark that only ever disappears is a dismissal, not a mark."""
    week = Week(db)
    week.confirm()

    week.confirm(confirmed=False)

    assert week.assignment().variant_confirmed_at is None
    assert week.codes() == [STAGE_FOR_EATER]


def test_the_written_portion_survives_un_confirming(db: Session) -> None:
    """It describes the plate, not the approval: a parent who takes back their
    confirmation has not unwritten what they had noted."""
    week = Week(db)
    week.confirm(variant="mixé, sans sel")

    week.confirm(confirmed=False)

    assert week.assignment().serving_variant == "mixé, sans sel"


def test_another_household_cannot_confirm_this_plate(db: Session) -> None:
    week = Week(db)
    other = Household(name="Autre foyer")
    db.add(other)
    db.commit()

    with pytest.raises(HTTPException) as refused:
        confirm_variant(
            week.plan.id,
            week.dish.id,
            VariantConfirmation(member_id=week.baby_id),
            db,
            other.id,
        )

    assert refused.value.status_code == 404
