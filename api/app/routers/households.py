"""Household endpoints.

Every query is scoped by the household derived from the session (invariant I6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import Household, HouseholdSettings, MealSlotConfig
from app.db.session import get_db
from app.schemas import (
    HouseholdOut,
    HouseholdSettingsOut,
    HouseholdSettingsUpdate,
    HouseholdUpdate,
    MealSlotOut,
    MealSlotUpdate,
)

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


def _load_settings(db: Session, household_id: CurrentHousehold) -> HouseholdSettings:
    """Provisioning creates this row, so a missing one means a household that
    predates it. Creating it here is cheaper than a startup migration and keeps
    every caller from having to handle a null."""
    settings = db.get(HouseholdSettings, household_id)
    if settings is None:
        settings = HouseholdSettings(household_id=household_id)
        db.add(settings)
        db.commit()
    return settings


@router.get("/settings", response_model=HouseholdSettingsOut)
def read_settings(db: DbDep, household_id: CurrentHousehold) -> HouseholdSettings:
    return _load_settings(db, household_id)


@router.patch("/settings", response_model=HouseholdSettingsOut)
def update_settings(
    payload: HouseholdSettingsUpdate, db: DbDep, household_id: CurrentHousehold
) -> HouseholdSettings:
    """One write path to the settings row, rather than a verb per field.

    The onboarding ends here too: a dedicated `POST /onboarding-complete` would
    be a second way to write the same row, and the settings screen has to be
    able to write it anyway.
    """
    settings = _load_settings(db, household_id)

    if payload.snacks_enabled is not None:
        settings.snacks_enabled = payload.snacks_enabled
    if payload.max_dishes_soft_limit is not None:
        settings.max_dishes_soft_limit = payload.max_dishes_soft_limit
    if payload.onboarding_complete is not None:
        # The server stamps the clock. The client says whether, never when.
        settings.onboarded_at = datetime.now(UTC) if payload.onboarding_complete else None

    db.commit()
    return settings


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
