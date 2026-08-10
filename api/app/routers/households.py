"""Household endpoints.

Every query is scoped by the household derived from the session (invariant I6).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import Household, MealSlotConfig
from app.db.session import get_db
from app.schemas import HouseholdOut, HouseholdUpdate, MealSlotOut, MealSlotUpdate

router = APIRouter(prefix="/household", tags=["household"])

DbDep = Annotated[Session, Depends(get_db)]


def _load(db: Session, household_id: CurrentHousehold) -> Household:
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "household not found")
    return household


@router.get("", response_model=HouseholdOut)
def read_household(db: DbDep, household_id: CurrentHousehold) -> Household:
    return _load(db, household_id)


@router.patch("", response_model=HouseholdOut)
def update_household(
    payload: HouseholdUpdate, db: DbDep, household_id: CurrentHousehold
) -> Household:
    household = _load(db, household_id)
    household.name = payload.name
    db.commit()
    return household


@router.get("/slots", response_model=list[MealSlotOut])
def read_slots(db: DbDep, household_id: CurrentHousehold) -> list[MealSlotConfig]:
    """The slot grid is declared at HOUSEHOLD level, not per member."""
    return list(
        db.scalars(
            select(MealSlotConfig)
            .where(MealSlotConfig.household_id == household_id)
            .order_by(MealSlotConfig.day_of_week, MealSlotConfig.meal_type)
        )
    )


@router.put("/slots", response_model=list[MealSlotOut])
def replace_slots(
    payload: list[MealSlotUpdate], db: DbDep, household_id: CurrentHousehold
) -> list[MealSlotConfig]:
    existing = {
        (slot.day_of_week, slot.meal_type): slot
        for slot in db.scalars(
            select(MealSlotConfig).where(MealSlotConfig.household_id == household_id)
        )
    }

    for entry in payload:
        key = (entry.day_of_week, entry.meal_type)
        if key in existing:
            existing[key].enabled = entry.enabled
        else:
            db.add(
                MealSlotConfig(
                    household_id=household_id,
                    day_of_week=entry.day_of_week,
                    meal_type=entry.meal_type,
                    enabled=entry.enabled,
                )
            )

    db.commit()
    return read_slots(db, household_id)
