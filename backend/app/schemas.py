"""Request and response models.

Note what is absent from every one of them: `household_id`. It is derived from
the authenticated identity (invariant I6) and appears in no endpoint signature.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.enums import (
    AllergenCode,
    ConstraintSeverity,
    DishSource,
    LifeStage,
    MealType,
    ReportCategory,
)
from app.domain.support_code import support_code


class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def support_code(self) -> str:
        """What the household reads out when it reports a bug.

        Computed here rather than in the browser so there is one definition of
        the format: the operator's `admin find` and the screen the user is
        reading from must not be able to disagree about what a code looks like.
        """
        return support_code(self.id)


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
    #: True when this assignment only holds BECAUSE of the variant — a `baby`
    #: on a recipe that does not carry that stage (§4.9). Zero of the 3 439
    #: catalogue recipes does, so this is every baby assignment today.
    #:
    #: Derived at serialisation, never stored: it is a fact about the recipe
    #: and the member, and storing it would let the two drift apart.
    requires_confirmation: bool = False
    #: When the parent confirmed. Null means "not yet", which is a real state:
    #: the variant is shown, marked pending, and not a meal to count on.
    variant_confirmed_at: datetime | None = None
    #: What the variant leaves out, by ingredient name. Checked against the
    #: recipe's own list before it was ever stored.
    removals: list[str] = Field(default_factory=list)


class VariantConfirmation(BaseModel):
    """A parent taking responsibility for one baby plate.

    Per member and per dish, never for a whole week: what is being confirmed is
    that THIS texture suits THIS child, and a blanket approval would be the
    system deciding again under a human's name.
    """

    member_id: uuid.UUID
    confirmed: bool = True


class DishOut(BaseModel):
    id: uuid.UUID
    label: str | None
    recipe_id: uuid.UUID | None
    eaters: list[DishEaterOut]
    #: The earlier meal of this week built on the same non-pantry ingredients,
    #: computed at read time (`domain.shared_ingredients`). A claim about a
    #: shopping list, never about a saucepan: a shared culinary base lives in
    #: the preparation steps, which I9 keeps out of the catalogue on purpose.
    #: Replaces `derived_from_dish_id`, which was documented as never filled —
    #: the column stays, for the day the generation declares an intent rather
    #: than the reader measuring a fact.
    shares_ingredients_with: uuid.UUID | None = None
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
    #: This dish was put here from the household's favourites rather than
    #: proposed. It explains why no serving variant follows it — without it the
    #: missing adaptation reads as a bug rather than as a consequence.
    placed_from_favorite: bool = False
    #: Somebody was warned that this dish carries an allergen, and chose it
    #: anyway. A warning one click makes disappear for ever is not a warning,
    #: and this meal is on a table four days later.
    allergen_override: bool = False
    #: Filled only when `allergen_override` is set: what was overridden, and
    #: whose it is. Computed at read time from the two tables that hold it, so
    #: a constraint added afterwards is reflected without a migration.
    allergen_conflicts: list[AllergenConflictOut] = Field(default_factory=list)


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

    The two flags travel with the write because only the client knows what the
    person was looking at: which list the dish was picked from, and whether a
    warning was on screen when they picked it. Both are cleared by any later
    write that does not set them — a dish chosen from the suggestions is no
    longer "depuis vos favoris", and the allergen it does not carry is no
    longer overridden.
    """

    label: str | None = Field(default=None, min_length=1, max_length=200)
    recipe_id: uuid.UUID | None = None
    #: Picked from the favourites list rather than from the suggestions.
    from_favorite: bool = False
    #: The person saw the allergen warning on this dish and chose it anyway.
    allergen_override: bool = False


class DishRegenerate(BaseModel):
    """Directed repair: the reason has value, it enriches the constraints."""

    reason: str = Field(min_length=1, max_length=500)


class SuggestionReportIn(BaseModel):
    """What a household says is wrong with a suggestion, for everyone.

    Distinct from `DishRegenerate`, which records a refusal as a constraint on
    THIS household. A category rather than free text, because a category can be
    grouped and acted on in one decision; the note is for the one report in
    twenty that says something a category cannot.
    """

    category: ReportCategory
    note: str | None = Field(default=None, max_length=280)


class DishRating(BaseModel):
    #: Rating a dish is also an implicit confirmation that it was eaten.
    value: int = Field(ge=-1, le=1)


class GuestCount(BaseModel):
    """One life stage and a head count. No member, nothing nominative."""

    model_config = ConfigDict(from_attributes=True)

    life_stage: LifeStage
    count: int = Field(ge=1, le=20)


class InvitationCreate(BaseModel):
    """Creating — or replacing — the invitation on one slot.

    There is no PATCH: the interface has a single edit form, and re-posting the
    same slot overwrites it. `guests` cannot be empty — an invitation with
    nobody coming is not a state worth storing.
    """

    week_start: date
    day_of_week: int = Field(ge=0, le=6)
    meal_type: MealType
    guests: list[GuestCount] = Field(min_length=1)
    #: Free text, one entry per dislike. A soft signal, never an exclusion.
    dislikes: list[str] = Field(default_factory=list)


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    week_start: date
    day_of_week: int
    meal_type: MealType
    guests: list[GuestCount]
    dislikes: list[str] = Field(default_factory=list)


class AllergenConflictOut(BaseModel):
    """An allergen a dish carries that someone here cannot eat.

    Computed here rather than in the client because both halves live in the
    database — `recipe_allergen` says what the dish contains, `dietary_constraint`
    says who cannot have it — and naming ONLY the allergen would send the reader
    off to check who it belongs to.

    Aversions are excluded. Red is what this product reserves for the allergen
    and for what cannot be undone; "n'aime pas les épinards" is neither, and
    spending the strongest signal on it would spend it everywhere.
    """

    allergen_code: AllergenCode
    #: Null on a household-wide constraint, which belongs to nobody in
    #: particular. The interface has a separate sentence for that case rather
    #: than inventing a name.
    member_name: str | None = None


class FavoriteOut(BaseModel):
    """A recipe the household means to cook again.

    Shaped like `AlternativeOut` on purpose: the slot panel lists the two side
    by side, under two headings, and a row that changed shape between the
    groups would read as a different kind of thing.
    """

    recipe_id: uuid.UUID
    title: str
    minutes: int | None = None
    complexity: int | None = None
    source_url: str | None = None
    #: Empty on the favourites tab, which does not flag allergens by design: a
    #: favourite is not a planned meal. The warning belongs to the moment the
    #: dish is put on a plate.
    conflicts: list[AllergenConflictOut] = Field(default_factory=list)


class FavoriteCreate(BaseModel):
    recipe_id: uuid.UUID


class ShoppingLineOut(BaseModel):
    """One thing to buy, and how much of it when the source said."""

    name: str
    #: Null when not one line carried a quantity. A real state and a different
    #: one from zero: the source wrote "du sel", so the list says it does not
    #: know rather than inventing an amount.
    amount: str | None = None


class ShoppingSectionOut(BaseModel):
    """One `FoodCategory`, in the order a shop is walked.

    Both labels travel: the client knows its locale, and the alternative —
    resolving it here — would put the request's language into a service that
    has no other reason to know it.
    """

    code: str
    label: str
    label_en: str | None = None
    lines: list[ShoppingLineOut] = Field(default_factory=list)


class ShoppingListOut(BaseModel):
    """What to buy for the meals someone picked, and what we cannot tell them.

    `pantry` carries names only. Nobody checks whether they have 200 g of salt;
    they check whether there is salt.

    `unparsed` is verbatim. Those lines have no ingredient, no category and no
    possible grouping — hiding them makes the list incomplete, folding them in
    makes it unreadable, so they are copied as written with the sentence that
    explains why.
    """

    week_start: date
    #: The SELECTION, not the week: the header of the copied text says how many
    #: meals it covers, and that has to be the meals it covers.
    meals: int
    days: int
    sections: list[ShoppingSectionOut] = Field(default_factory=list)
    pantry: list[str] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list)
    #: At least one chosen meal holds a dish with no recipe, so its ingredients
    #: are not here. Saying nothing would be the worst case — a list somebody
    #: believes is complete.
    missing_recipe: bool = False
