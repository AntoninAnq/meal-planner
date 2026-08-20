"""Request and response models.

Note what is absent from every one of them: `household_id`. It is derived from
the authenticated identity (invariant I6) and appears in no endpoint signature.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AllergenCode, ConstraintSeverity, DishSource, LifeStage, MealType


class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class HouseholdUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class HouseholdSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snacks_enabled: bool
    max_dishes_soft_limit: int
    onboarded_at: datetime | None


class HouseholdSettingsUpdate(BaseModel):
    """Every field optional: this is a patch, not a replacement."""

    snacks_enabled: bool | None = None
    max_dishes_soft_limit: int | None = Field(default=None, ge=1, le=6)
    #: An intent, not a timestamp. A client must never write a server clock
    #: value — it would be wrong by its own skew, and nothing stops it being
    #: arbitrary. `True` stamps now; `False` clears it, which is what makes the
    #: onboarding replayable during development.
    onboarding_complete: bool | None = None


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
    #: The INTERPRETED constraints, structured — not their labels.
    #:
    #: They used to arrive as `list[str]`: the front received `{kind, label,
    #: detail}`, showed it, had it confirmed, then flattened it to prose one
    #: line before the only place the structure is useful. The model was then
    #: handed "j'ai du jambon dans le frigo" and asked to find, among sixty
    #: candidates, the ones containing ham — a search the pre-filter does in
    #: SQL. §6.3 draws that line: what can be computed is computed.
    constraints: list[InterpretedConstraint] = Field(default_factory=list)
    #: Language of the dish titles the model writes. Sent by the frontend,
    #: which knows the active locale.
    language: str = "fr"


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
    #: Where the dish came from. The interface needs it for one reason: a dish
    #: someone typed themselves is the only one no filter can vouch for, and
    #: `UX-V0.md` §15 keeps a mark on it after the global notice disappears.
    source: DishSource = DishSource.LLM_SUGGESTION
    #: Declared prep + cooking, and the computed 1..3 rating. Null on the fifth
    #: of the catalogue that declares neither — the card then says nothing
    #: rather than implying a recipe is quick.
    minutes: int | None = None
    complexity: int | None = None
    #: The address of the recipe at its source, for a catalogue dish. I9 keeps
    #: the facts and sends people to the author for the rest, so this link is
    #: not a convenience — it is the half of the bargain the interface owes.
    #: Null on a dish someone typed themselves: there is nothing to link to.
    source_url: str | None = None


class SlotGuestsOut(BaseModel):
    """An anonymous count, never an entity.

    Guests are transitory — storing them as members would skew anti-repetition
    and portions all year long. But a meal cooked for nine that displays as a
    meal for three is misleading, so the count survives for the interface, and
    for nothing else: no planning code reads it.
    """

    life_stage: LifeStage
    count: int


class PlanSlotOut(BaseModel):
    day_of_week: int
    meal_type: MealType
    dishes: list[DishOut]
    guests: list[SlotGuestsOut] = Field(default_factory=list)


class ViolationOut(BaseModel):
    """What the re-validation rejected, addressed to two different readers.

    `code` and `detail` are for the logs and the eval harness. `day_of_week`
    and `meal_type` are for the interface: the only useful reaction to a
    violation is per slot — regenerate that one, or write the dish yourself —
    so a message that cannot point at a meal is less useful than silence.
    """

    code: str
    detail: str
    day_of_week: int | None = None
    meal_type: MealType | None = None


class MealPlanOut(BaseModel):
    id: uuid.UUID
    week_start: date
    #: Stamped on every generation. It is what lets a client that stopped
    #: waiting tell the plan it was already looking at from the one that has
    #: just landed.
    generated_at: datetime
    slots: list[PlanSlotOut]
    #: Present when the model never produced a plan inside the envelope. The
    #: plan is returned anyway, with what is wrong stated plainly.
    violations: list[ViolationOut] = Field(default_factory=list)


class AlternativeOut(BaseModel):
    """A candidate the pre-filter produced and the model passed over.

    Carries what the card shows, so choosing one costs no second request. The
    effort fields are null on the 18 % of the catalogue that declares neither a
    time nor a step count — the interface then says nothing rather than
    implying a recipe is quick.
    """

    recipe_id: uuid.UUID
    title: str
    minutes: int | None = None
    complexity: int | None = None
    ingredients: list[str] = Field(default_factory=list)
    #: Same reason as on a planned dish: choosing an alternative is exactly the
    #: moment someone wants to see what they are choosing.
    source_url: str | None = None


class DishReplace(BaseModel):
    """Either a catalogue recipe, or a title written by hand.

    The second is not a fallback: `UX-V0.md` §6 found that someone often knows
    what they want to eat, and letting them write it beats any negotiation with
    a model. A hand-written dish is also the one thing no filter can vouch for,
    which is why it stays marked in the interface (§15).
    """

    label: str | None = Field(default=None, min_length=1, max_length=200)
    recipe_id: uuid.UUID | None = None


class DishRegenerate(BaseModel):
    """Directed repair: the reason has value, it enriches the constraints."""

    reason: str = Field(min_length=1, max_length=500)


class DishRating(BaseModel):
    #: Rating a dish is also an implicit confirmation that it was eaten.
    value: int = Field(ge=-1, le=1)
