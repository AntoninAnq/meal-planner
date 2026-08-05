"""Request and response models.

Note what is absent from every one of them: `household_id`. It is derived from
the authenticated identity (invariant I6) and appears in no endpoint signature.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AllergenCode, ConstraintSeverity, LifeStage, MealType


class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class HouseholdUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MealSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    day_of_week: int = Field(ge=0, le=6)
    meal_type: MealType
    enabled: bool


class MealSlotUpdate(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    meal_type: MealType
    enabled: bool


class MemberCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    birth_date: date | None = None
    #: Optional. When a birth date is given the derived stage is used as the
    #: initial value; it is a starting point, not an automatic transition.
    life_stage: LifeStage | None = None


class MemberUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    birth_date: date | None = None


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    birth_date: date | None
    life_stage: LifeStage


class PendingTransitionOut(BaseModel):
    """A stage change awaiting parental confirmation (§4.3).

    Never applied on its own: crossing BABY -> YOUNG_CHILD widens what is
    allowed, and nobody has judged whether this particular child is ready.
    """

    member_id: uuid.UUID
    current: LifeStage
    proposed: LifeStage


class LifeStageConfirmation(BaseModel):
    confirmed: LifeStage


class DietaryConstraintCreate(BaseModel):
    allergen_code: AllergenCode | None = None
    #: Severity decides the SCOPE of the filter (§4.6). Defaults to the safe side.
    severity: ConstraintSeverity = ConstraintSeverity.SEVERE_ALLERGY
    note: str | None = None


class DietaryConstraintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    member_id: uuid.UUID
    allergen_code: AllergenCode | None
    severity: ConstraintSeverity
    note: str | None
