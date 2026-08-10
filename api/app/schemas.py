"""Request and response models.

Note what is absent from every one of them: `household_id`. It is derived from
the authenticated identity (invariant I6) and appears in no endpoint signature.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

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
    """A stage change awaiting parental confirmation.

    Never applied on its own: crossing BABY -> YOUNG_CHILD widens what is
    allowed, and nobody has judged whether this particular child is ready.
    """

    member_id: uuid.UUID
    current: LifeStage
    proposed: LifeStage


class LifeStageConfirmation(BaseModel):
    confirmed: LifeStage


class DietaryConstraintCreate(BaseModel):
    """One concept of constraint, whose member is optional.

    `member_id = None` means the whole household ("we don't eat that here") and
    is accepted for AVERSIONS only: an allergy without someone it belongs to is
    meaningless, and its household scope comes from its severity.
    """

    member_id: uuid.UUID | None = None
    allergen_code: AllergenCode | None = None
    #: Free text, used by V0 aversions — there is no ingredient referential yet.
    label: str | None = Field(default=None, max_length=120)
    #: Severity decides the SCOPE of the filter. Defaults to the safe side.
    severity: ConstraintSeverity = ConstraintSeverity.SEVERE_ALLERGY
    note: str | None = None


class DietaryConstraintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    member_id: uuid.UUID | None
    allergen_code: AllergenCode | None
    label: str | None
    severity: ConstraintSeverity
    note: str | None


# --- Planning ----------------------------------------------------------------


class InterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class InterpretedConstraint(BaseModel):
    kind: str
    label: str
    detail: str | None = None


class InterpretResponse(BaseModel):
    """Shown to the user and corrected BEFORE generating.

    Never applied invisibly: a misread intent would produce a wrong plan the
    user cannot diagnose or correct except by rephrasing blindly.
    """

    constraints: list[InterpretedConstraint]


class WeekScope(BaseModel):
    type: Literal["week"] = "week"
    week_start: date


class SlotScope(BaseModel):
    type: Literal["slot"] = "slot"
    day: date
    meal_type: MealType


class GuestGroupIn(BaseModel):
    """Transitory. Never stored, never a member."""

    life_stage: LifeStage
    count: int = Field(ge=1, le=20)
    #: Excludes the allergen from the WHOLE slot, for everyone.
    excluded_allergens: list[AllergenCode] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)


class GeneratePlanRequest(BaseModel):
    """One parameterised operation — there is no separate 'guests' endpoint.

    Two endpoints sharing 90% of their logic always diverge: a fix applied to
    one, forgotten on the other.
    """

    scope: WeekScope | SlotScope = Field(discriminator="type")
    member_ids: list[uuid.UUID] | None = None
    guests: list[GuestGroupIn] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class DishEaterOut(BaseModel):
    member_id: uuid.UUID
    #: How to serve this person, not whether they may eat it.
    serving_variant: str | None = None


class DishOut(BaseModel):
    id: uuid.UUID
    label: str | None
    recipe_id: uuid.UUID | None
    eaters: list[DishEaterOut]
    #: Always null in V0: overlap is not computable without ingredients.
    derived_from_dish_id: uuid.UUID | None = None


class PlanSlotOut(BaseModel):
    day_of_week: int
    meal_type: MealType
    dishes: list[DishOut]


class MealPlanOut(BaseModel):
    id: uuid.UUID
    week_start: date
    slots: list[PlanSlotOut]
    #: Present when the model never produced a plan inside the envelope. The
    #: plan is returned anyway, with what is wrong stated plainly.
    violations: list[str] = Field(default_factory=list)


class DishReplace(BaseModel):
    label: str = Field(min_length=1, max_length=200)


class DishRegenerate(BaseModel):
    """Directed repair: the reason has value, it enriches the constraints."""

    reason: str = Field(min_length=1, max_length=500)


class DishRating(BaseModel):
    #: Rating a dish is also an implicit confirmation that it was eaten.
    value: int = Field(ge=-1, le=1)
