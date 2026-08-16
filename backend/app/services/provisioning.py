"""First-login provisioning.

Signing in with an identity that has no household creates one — that is the
signup path. A new identity gets its own empty household and no visibility on
anyone else's, so this is safe to leave open.

The default slot grid is "weekday dinners + full weekend": in the typical
French case the school canteen covers weekday lunches.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Household, HouseholdAccess, HouseholdSettings, MealSlotConfig
from app.domain.enums import MealType

WEEKDAYS = range(0, 5)  # Monday..Friday
WEEKEND = range(5, 7)  # Saturday, Sunday


def provision_household(db: Session, *, auth_subject: str, name: str = "Mon foyer") -> Household:
    household = Household(name=name)
    db.add(household)
    db.flush()

    db.add(HouseholdAccess(auth_subject=auth_subject, household_id=household.id))
    db.add(HouseholdSettings(household_id=household.id))

    for day in WEEKDAYS:
        db.add(
            MealSlotConfig(
                household_id=household.id,
                day_of_week=day,
                meal_type=MealType.DINNER,
                enabled=True,
            )
        )
    for day in WEEKEND:
        for meal_type in (MealType.LUNCH, MealType.DINNER):
            db.add(
                MealSlotConfig(
                    household_id=household.id,
                    day_of_week=day,
                    meal_type=meal_type,
                    enabled=True,
                )
            )

    db.commit()
    return household
