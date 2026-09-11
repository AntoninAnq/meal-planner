"""SQLAlchemy models.

Households, access, members, constraints, slots, configuration, plans, history
and snacks came with phase 0. The catalogue — recipes, ingredients, categories
and the proposal queue — arrives with phase 1 (`docs/ARCHITECTURE.md` §8.2).

The `recipe_id` columns on plan and history rows existed from the start without
a foreign key, so the V0 write shape never had to change; migration 0006 adds
the constraints now that `recipe` exists.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.enums import (
    AllergenCode,
    ConstraintSeverity,
    DishSource,
    DishType,
    GenerationKind,
    LifeStage,
    MealType,
    OperatorLevel,
    ProposalStatus,
    RecipeSourceType,
    ReportCategory,
)


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _pg_enum(python_enum: type, name: str) -> Enum:
    """Persist enum VALUES, not member names.

    SQLAlchemy stores `.name` by default, which would put `BABY` in the database
    while every other layer (JSON payloads, fixtures, the eval golden files)
    speaks `baby`. `values_callable` keeps a single spelling everywhere.
    """
    return Enum(
        python_enum,
        name=name,
        native_enum=True,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


life_stage_enum = _pg_enum(LifeStage, "life_stage")
meal_type_enum = _pg_enum(MealType, "meal_type")
severity_enum = _pg_enum(ConstraintSeverity, "constraint_severity")
dish_source_enum = _pg_enum(DishSource, "dish_source")
allergen_enum = _pg_enum(AllergenCode, "allergen_code")
operator_level_enum = _pg_enum(OperatorLevel, "operator_level")
report_category_enum = _pg_enum(ReportCategory, "report_category")
recipe_source_enum = _pg_enum(RecipeSourceType, "recipe_source_type")
proposal_status_enum = _pg_enum(ProposalStatus, "proposal_status")
dish_type_enum = _pg_enum(DishType, "dish_type")
generation_kind_enum = _pg_enum(GenerationKind, "generation_kind")


class Household(Base):
    __tablename__ = "household"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: This household's ceiling on model calls per window. NULL — the default —
    #: means the one in `Settings`, which is the rate card everyone gets.
    #:
    #: Here and NOT on `household_settings`, which holds what the household
    #: itself chooses through `/household/settings`. This is what the OPERATOR
    #: allows — a different owner, so a different table.
    #:
    #: Not because the endpoint would leak it: that route names its fields one
    #: by one, in and out, so a new column reaches nobody until three separate
    #: edits say it should. The reason is that a reader looking for "what this
    #: household picked" must not find a policy they cannot change, and the
    #: next person to add a field to the settings patch must not have to
    #: remember which of its columns are theirs.
    #:
    #: Three uses, one column. A paid tier is a high ceiling, not the absence of
    #: one — an account whose session is stolen spends the operator's money
    #: either way, so "unlimited" is a ceiling nobody should offer. A suspected
    #: bot gets a low one, which throttles without cutting off. And 0 is a real
    #: value: no generation at all, while the household can still read the weeks
    #: it already has. Cutting someone off entirely is `HouseholdAccess.
    #: revoked_at`, a different decision with a different blast radius.
    generation_limit_override: Mapped[int | None] = mapped_column(SmallInteger)

    members: Mapped[list[Member]] = relationship(back_populates="household")
    settings: Mapped[HouseholdSettings | None] = relationship(back_populates="household")


class HouseholdAccess(Base):
    """Who may act on a household.

    `auth_subject` is PREFIXED by its mechanism — `google:117482…`,
    `password:antonin`, `email:antonin@…`. Without the prefix, two mechanisms
    eventually produce the same string for two different people. With it, adding
    a mechanism means writing one verification function that returns an
    `auth_subject`: no endpoint, no query and no test moves.

    Several rows per household: both parents will each want their own access
    within six months, and adding the relation afterwards means touching every
    query.

    Holds no secret and no personal data.
    """

    __tablename__ = "household_access"

    auth_subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: Set to cut this identity off. NULL — the default — means active.
    #:
    #: The row SURVIVES revocation, and that is the whole design: `callback`
    #: provisions a household exactly when it finds no access row, so deleting
    #: would let the same identity walk back in on the next login. Revoked but
    #: present means recognised, refused, and unable to re-register.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Operator(Base):
    """Who may run this instance — a different question from who owns a household.

    Its own table rather than a column on `household_access`, because operating
    the instance is not a property of a link to one household: retagging a
    recipe changes the catalogue for everyone. Someone may operate without ever
    having generated a week, and losing the operator right must not touch their
    household.

    **Two levels, and the asymmetry is the reason.** A `contributor` retags —
    reversible, hurts nobody, and it is the work one recruits help for. Only an
    `owner` grants, because granting is privilege escalation: a helper who can
    add helpers can remove the person who invited them. One level would force a
    choice between not delegating and handing over the keys.

    `granted_by` is nullable for exactly one row: the first owner, created by
    `python -m app.admin grant` before any interface exists. Every other grant
    records who made it — a privilege table that cannot say who let someone in
    is one you have to guess about later, and the column costs nothing now.

    No email here either (§11.7). Access is granted to an identity Google has
    already verified, found by the support code the person reads in their own
    settings screen — so nothing needs to be pre-authorised, and no address is
    stored to make it possible.
    """

    __tablename__ = "operator"

    auth_subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    level: Mapped[OperatorLevel] = mapped_column(operator_level_enum)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: The `auth_subject` that granted this one. NULL only for the bootstrap.
    granted_by: Mapped[str | None] = mapped_column(String(255))


class SuggestionReport(Base):
    """A household saying a suggestion is wrong for everyone, not just for them.

    The other channel — `Proposer autre chose` — records a refusal as a
    constraint on one household. This one says the catalogue is at fault, and
    its resolution is a change every household sees.

    **Keyed on the recipe, not on the dish.** The person clicks a dish in their
    week, but the defect belongs to the catalogue entry behind it, and the queue
    has to group ten reports of the same tart into one decision. A hand-written
    dish has no recipe and cannot be reported: there is nothing catalogue-wide
    to fix, and its author already knows.

    One row per household and recipe: re-reporting corrects the category rather
    than adding a voice. A queue ranked by how many DIFFERENT households
    complained is a signal; one ranked by clicks is a measure of persistence.
    """

    __tablename__ = "suggestion_report"
    __table_args__ = (
        UniqueConstraint("household_id", "recipe_id", name="uq_report_household_recipe"),
    )

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[ReportCategory] = mapped_column(report_category_enum)
    #: Optional and short. The category is what the queue sorts on; this is for
    #: the one report in twenty that says something a category cannot.
    note: Mapped[str | None] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: Set when an operator has acted. The row survives, so the same recipe
    #: reported again is visibly a second complaint and not a first.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(255))


class HouseholdFavorite(Base):
    """A dish the household means to cook again.

    **Not the same signal as "did you like it".** `MealHistory.rating` grades a
    meal that has happened; this says what the household wants to see proposed
    again. Two different questions, asked at two different moments, and the
    answers do not imply one another — a dinner everyone liked can be one
    nobody wants twice a month, and a favourite can have gone badly the one
    time it was tried. They share no storage and no display.

    **Only a catalogue recipe can be one.** A dish the model proposed on its own
    never becomes a recipe (I7), so it has no page to come back to and nothing
    to point at. There is no greyed-out heart for those: the rule is explained
    once, on the empty state, and nowhere else.

    **At the household, not at the account.** The plan is the household's,
    `household_access` already carries the sharing, and two parents planning
    together do not have two lists.

    `ondelete="CASCADE"` on the recipe, unlike `meal_history`, which is
    `RESTRICT`. A favourite is not a historical fact: if a recipe leaves the
    catalogue there is nothing left to cook, and the favourite goes with it.
    A meal that WAS eaten stays true whatever happens to the catalogue.
    """

    __tablename__ = "household_favorite"
    __table_args__ = (
        UniqueConstraint("household_id", "recipe_id", name="uq_favorite_household_recipe"),
    )

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), index=True
    )
    #: What the list is ordered by, most recent first. Nothing else reads it.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HouseholdExclusion(Base):
    """A dish the household never wants proposed again.

    The other half of `HouseholdFavorite`, and shaped like it: at the household,
    one row per recipe, gone with the recipe. `SqlCatalogue` reads it and
    withholds these from every pool it builds for this household — the
    generation and the alternatives alike.

    It replaces a rating nothing ever read. A household that answered "Non" to
    "Ce plat a plu ?" saw the dish come back the next week; this one does not.

    A recipe is never both a favourite and withheld: the two routers each clear
    the other row, so the latest answer is the one that holds.
    """

    __tablename__ = "household_exclusion"
    __table_args__ = (
        UniqueConstraint("household_id", "recipe_id", name="uq_exclusion_household_recipe"),
    )

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), index=True
    )
    #: What the list is ordered by, most recent first. Nothing else reads it.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HouseholdSettings(Base):
    __tablename__ = "household_settings"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), primary_key=True
    )
    snacks_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Soft penalty, never a hard constraint. The only hard bound is
    # "at worst one dish per member", which is trivially satisfiable.
    max_dishes_soft_limit: Mapped[int] = mapped_column(SmallInteger, default=2)
    # Null until the onboarding is finished. It cannot be derived from "this
    # household has members": someone interrupted after adding them would never
    # be asked the allergy question, which is the one thing the onboarding
    # exists to ask. A derivation also cannot tell "block 2 of 3" from "not
    # started", so the flow would not be resumable.
    onboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    household: Mapped[Household] = relationship(back_populates="settings")


class Member(Base):
    __tablename__ = "member"

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(80))
    birth_date: Mapped[date | None] = mapped_column(Date)

    #: EFFECTIVE stage, confirmed by a parent. `birth_date` only ever produces a
    #: proposal — crossing BABY -> YOUNG_CHILD widens what is allowed, so
    #: it is never applied silently.
    life_stage: Mapped[LifeStage] = mapped_column(life_stage_enum)
    life_stage_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    household: Mapped[Household] = relationship(back_populates="members")
    constraints: Mapped[list[DietaryConstraint]] = relationship(back_populates="member")


class DietaryConstraint(Base):
    """Severity decides the SCOPE of the filter.

    Default severity when the user does not say is SEVERE_ALLERGY: an
    over-constrained household gets slightly dull menus, an under-constrained
    one gets an emergency-room visit.
    """

    __tablename__ = "dietary_constraint"
    __table_args__ = (
        CheckConstraint(
            "(allergen_code IS NOT NULL) OR (ingredient_id IS NOT NULL) OR (label IS NOT NULL)",
            name="ck_dietary_constraint_target",
        ),
        # Only an aversion may float free of a member. An allergy without
        # someone it belongs to is meaningless — and its household scope comes
        # from its SEVERITY, not from its storage.
        CheckConstraint(
            "(member_id IS NOT NULL) OR (severity = 'aversion')",
            name="ck_dietary_constraint_member_required",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    #: NULL = applies to the whole household ("we don't eat that here").
    #: Refinement goes one way only: household -> member, never the reverse.
    member_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("member.id", ondelete="CASCADE"), index=True
    )
    allergen_code: Mapped[AllergenCode | None] = mapped_column(allergen_enum)
    # FK added in phase 1, with the ingredient referential.
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    #: Free text, used by V0 aversions — there is no ingredient referential yet.
    label: Mapped[str | None] = mapped_column(String(120))
    severity: Mapped[ConstraintSeverity] = mapped_column(
        severity_enum, default=ConstraintSeverity.SEVERE_ALLERGY
    )
    note: Mapped[str | None] = mapped_column(Text)

    #: Optional: a household-wide aversion has no member.
    member: Mapped[Member | None] = relationship(back_populates="constraints")


class MealSlotConfig(Base):
    """Which slots this household wants planned. Household level, not per member."""

    __tablename__ = "meal_slot_config"
    __table_args__ = (
        UniqueConstraint("household_id", "day_of_week", "meal_type", name="uq_meal_slot_config"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_meal_slot_day"),
    )

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday
    meal_type: Mapped[MealType] = mapped_column(meal_type_enum)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PortionCoefficient(Base):
    """Configurable, never hardcoded (invariant I8)."""

    __tablename__ = "portion_coefficient"

    life_stage: Mapped[LifeStage] = mapped_column(life_stage_enum, primary_key=True)
    coefficient: Mapped[Decimal] = mapped_column(Numeric(4, 2))


class LifeStageThreshold(Base):
    """Upper bound in months, exclusive. NULL = open-ended."""

    __tablename__ = "life_stage_threshold"

    life_stage: Mapped[LifeStage] = mapped_column(life_stage_enum, primary_key=True)
    upper_bound_months: Mapped[int | None] = mapped_column(Integer)


class MealPlan(Base):
    __tablename__ = "meal_plan"
    __table_args__ = (UniqueConstraint("household_id", "week_start", name="uq_meal_plan_week"),)

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    week_start: Mapped[date] = mapped_column(Date)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    #: The free-text intent the user typed, kept for the eval harness and for
    #: reproducing a plan.
    generation_input: Mapped[str | None] = mapped_column(Text)
    #: What the re-validation rejected, stored with the plan it describes. The
    #: week view loads through GET, so violations that lived only in the POST
    #: response vanished on the first reload — taking with them the one thing
    #: that said this plan is incomplete.
    violations: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    #: `{"5-dinner": [{"life_stage": "teen_adult", "count": 6}]}` — an anonymous
    #: count per slot, for display only. Guests still never become members, and
    #: nothing in the planner reads this: it exists so a meal cooked for nine
    #: does not silently show up as a meal for three.
    slot_guests: Mapped[dict[str, list[dict[str, object]]]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )

    dishes: Mapped[list[PlannedDish]] = relationship(back_populates="plan")


class PlannedDish(Base):
    """One dish on one slot. A slot carries 1..N of these."""

    __tablename__ = "planned_dish"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_planned_dish_day"),
        CheckConstraint(
            "(recipe_id IS NOT NULL) OR (free_text_label IS NOT NULL)",
            name="ck_planned_dish_identity",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meal_plan.id", ondelete="CASCADE"), index=True
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    meal_type: Mapped[MealType] = mapped_column(meal_type_enum)
    # RESTRICT, not SET NULL: `ck_planned_dish_identity` requires one of
    # recipe_id / free_text_label, and a catalogue dish has no label — blanking
    # the reference would leave a row that says nothing was planned. Retiring a
    # source means deactivating its recipes, not deleting rows someone ate.
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipe.id", ondelete="RESTRICT")
    )
    # Used by V0, where the model only proposes dish titles.
    free_text_label: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[DishSource] = mapped_column(dish_source_enum)
    position: Mapped[int] = mapped_column(SmallInteger, default=0)
    #: Two preparations sharing a base. Drawn now, always NULL
    #: until the catalogue exists: overlap is not computable without ingredients.
    derived_from_dish_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("planned_dish.id", ondelete="SET NULL")
    )
    #: Put here from the household's favourites rather than proposed. It is what
    #: explains the absence of a serving variant on a slot that had one: the
    #: favourite replaced the proposal, and nothing recomputed the small
    #: portion. Without it the missing adaptation reads as a bug.
    placed_from_favorite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: Someone was told this dish carries an allergen somebody here cannot eat,
    #: and chose it anyway. Stored rather than shown once: a warning that one
    #: click removes for ever is not a warning, and this meal is on a table four
    #: days later.
    allergen_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    plan: Mapped[MealPlan] = relationship(back_populates="dishes")
    # `passive_deletes` hands the cascade to the database, which already has
    # ON DELETE CASCADE. Without it the ORM tries to blank out
    # `planned_dish_member.planned_dish_id` — half of that table's primary key —
    # and raises. It only shows up when a slot that ALREADY had dishes is
    # regenerated, which is exactly what the slot panel does.
    eaters: Mapped[list[PlannedDishMember]] = relationship(
        back_populates="dish", cascade="all, delete-orphan", passive_deletes=True
    )


class PlannedDishMember(Base):
    """Who eats which dish — and what makes per-member anti-repetition possible.

    A "group" is the set of members sharing a dish on a given slot: emergent,
    recomputed every slot, never stored as a partition of the household.
    """

    __tablename__ = "planned_dish_member"

    planned_dish_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planned_dish.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("member.id", ondelete="CASCADE"), primary_key=True
    )
    #: Same preparation, different plate. "sans olives",
    #: "part prélevée avant salage et mixée". Carried by the ASSIGNMENT because
    #: two people can have different variants on the same dish.
    #:
    #: It describes HOW to serve, never WHETHER the assignment is allowed: a
    #: variant can never make acceptable an assignment that was not (I1).
    #:
    #: ONE exception, and only for the `baby` stage (§4.9). No catalogue recipe
    #: carries `baby` — zero of 3 439 — so a variant is the only way that stage
    #: can be fed at all. There, and there alone, the variant DOES open the
    #: assignment, and `variant_confirmed_at` is what makes that legitimate.
    serving_variant: Mapped[str | None] = mapped_column(String(200))

    #: When the parent confirmed this variant. NULL means "not yet", which is a
    #: real state: the variant is shown, marked pending, and never counted as a
    #: meal the household can rely on.
    #:
    #: Same shape as `Ingredient.confirmed_at` and for the same reason — I1
    #: forbids a LLM deciding, not a human, but the difference has to be
    #: recorded where the code can read it, or "the parent agreed" is a claim
    #: nobody can check.
    variant_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dish: Mapped[PlannedDish] = relationship(back_populates="eaters")
    removals: Mapped[list[PlannedDishMemberRemoval]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class PlannedDishMemberRemoval(Base):
    """What the variant takes out of the dish, as ingredient ids.

    Structured rather than prose, and the reason is measured. Asked in free
    text for an aversion, the model wrote "sans tomate" beside an eater on nine
    dishes, several of which contained no tomato — nothing could catch it. An
    ingredient id can be checked against the recipe's own list before it ever
    reaches a screen; a sentence cannot.

    It also keeps the allergens computable: removing an ingredient can only
    take allergens away, never add one, so a variant is at worst as safe as the
    dish it comes from.
    """

    __tablename__ = "planned_dish_member_removal"

    planned_dish_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    member_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredient.id", ondelete="RESTRICT"), primary_key=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["planned_dish_id", "member_id"],
            ["planned_dish_member.planned_dish_id", "planned_dish_member.member_id"],
            ondelete="CASCADE",
        ),
    )

    assignment: Mapped[PlannedDishMember] = relationship(back_populates="removals")


class Invitation(Base):
    """A meal with guests, kept BESIDE the plan and never inside it.

    Guests stay transitory — they never become members, because people who eat
    here twice a year would otherwise skew anti-repetition, portions and stage
    proposals all year long. `meal_plan.slot_guests` already carries an
    anonymous head count for the interface; this is a different thing. An
    invitation is something the household *created* and comes back to — Saturday
    dinner with the in-laws, who is coming and what they will not eat — and it
    outlives any one generation of that slot. Regenerating the meal, or clearing
    it, leaves the invitation standing.

    It is its own entity on purpose: a seating plan will hang off it later. The
    generation reads `guests` for portions and `dislikes` as a soft signal, the
    same way a household aversion nudges without excluding — nothing about a
    guest is stored beyond the count and those free-text tastes.
    """

    __tablename__ = "invitation"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_invitation_day"),
        # One invitation per slot: "the Saturday dinner", not a list of them.
        # Re-creating it for the same slot replaces it, which is what the
        # interface's single edit form expects to find.
        UniqueConstraint(
            "household_id",
            "week_start",
            "day_of_week",
            "meal_type",
            name="uq_invitation_slot",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    week_start: Mapped[date] = mapped_column(Date)
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    meal_type: Mapped[MealType] = mapped_column(meal_type_enum)
    #: `[{"life_stage": "teen_adult", "count": 6}]` — the same shape as
    #: `meal_plan.slot_guests`, read for portions at generation time. Never a
    #: member, never anything nominative: a number and an enum.
    guests: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    #: The guests' tastes, free text, one entry per dislike. A soft signal like a
    #: household aversion: it nudges the suggestion, it never excludes a dish.
    dislikes: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MealHistory(Base):
    """What was actually eaten, per member.

    Invariant I7: V0 suggestions land here with source=LLM_SUGGESTION and are
    never promoted to catalogue recipes. This history is also the best catalogue
    seed there is — after three weeks you know which dishes actually recur.
    """

    __tablename__ = "meal_history"

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("member.id", ondelete="CASCADE"), index=True
    )
    eaten_on: Mapped[date] = mapped_column(Date, index=True)
    meal_type: Mapped[MealType] = mapped_column(meal_type_enum)
    # History is a record. A recipe that someone actually ate cannot be made to
    # disappear from it by a catalogue cleanup.
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipe.id", ondelete="RESTRICT")
    )
    free_text_label: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[DishSource] = mapped_column(dish_source_enum)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    #: History is implicit in V0: a past planned dish counts as
    #: eaten, and nothing is ever confirmed. Rating a dish will fill this later
    #: — rating IS an implicit confirmation — with no migration needed, and the
    #: eval harness can then tell assumed history from real history.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SnackSuggestion(Base):
    """Separate object, optional module.

    A snack has no dish, no multi-group assignment and no overlap. Modelling it
    as a regular slot would pollute the planner with special cases.
    """

    __tablename__ = "snack_suggestion"

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    suggested_on: Mapped[date] = mapped_column(Date, index=True)
    label: Mapped[str] = mapped_column(String(200))
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipe.id", ondelete="RESTRICT")
    )
    source: Mapped[DishSource] = mapped_column(dish_source_enum)


class GenerationLog(Base):
    """One row per model call a household paid for. Append-only.

    Three jobs, and it exists because none of them can be done without it:

      * **The quota.** Signing up is open — any Google identity that arrives
        gets a household (`provision_household`). Nothing else stands between a
        stranger, or a loop, and a metered API. This table is the only
        mechanism that bounds what one household can spend in a day.
      * **The bill.** Tokens and `model_id` are what turn "it seems to cost
        something" into a figure per household per month — the number pricing
        will need, and the one the model comparison of §14.6 needs to compare
        anything but latency.
      * **Usage.** How often a real household regenerates is a product fact
        nothing else records.

    **Counting `meal_plan` rows would not have worked.** A regeneration
    overwrites the week in place — same row, same id — so the table that holds
    the plans holds no trace of the second, third and tenth attempt. Those are
    exactly the calls a quota exists to count.

    Written even when the call FAILED, and the tokens are then the ones the
    exhausted attempts really consumed. A failed generation is the most
    expensive kind — three attempts, three prompts — so a log that only records
    successes understates the bill precisely where it is highest, and leaves
    the cheapest way to burn an API key uncounted.
    """

    __tablename__ = "generation_log"
    __table_args__ = (
        Index("ix_generation_log_household_created", "household_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE")
    )
    #: Indexed WITH `household_id`, because the quota only ever asks one
    #: question: how many rows for this household since a moment. On the
    #: household alone the index stops being useful the day a tester has
    #: thousands of rows — which is the day the quota matters.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    kind: Mapped[GenerationKind] = mapped_column(generation_kind_enum)
    #: Cumulative over every attempt, not just the accepted one.
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=1)
    #: What the provider says it ran, not what was configured. The two differ
    #: the day an alias moves, and the bill follows the first.
    model_id: Mapped[str] = mapped_column(String(80), default="")
    #: False when the call raised. Kept as a column rather than inferred from
    #: zero tokens: a provider that was unreachable also spent zero, and the
    #: two are not the same fact.
    succeeded: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# Catalogue — phase 1
# ---------------------------------------------------------------------------


class FoodCategory(Base):
    """`legumes_secs`, `fish`, `red_meat`, `starch`, `green_vegetable`…

    Feeds the rotation signal of §6.2: "23 days since legumes". A signal, never
    a filter — the planner must be able to ignore it.
    """

    __tablename__ = "food_category"

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(60), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    #: The shopping list prints these as section headings, so they are the one
    #: piece of catalogue data a reader sees in their own language. A column
    #: rather than message keys: the codes live in `db/ingredients.yaml` and are
    #: reviewed as a Git diff, and splitting their labels across two files would
    #: let a category exist with no heading. Nullable for the rows that predate
    #: it — the reader falls back on the French label, which is a heading in the
    #: wrong language rather than a section with no name.
    label_en: Mapped[str | None] = mapped_column(String(120))


class Ingredient(Base):
    """The referential the whole allergen filter rests on.

    Seeded from `db/ingredients.yaml`, reviewed as a Git diff, never edited in
    place through an interface: on the data the safety filter depends on,
    knowing who decided what beats a form (§7.5).

    `normalized_name` is what matching reads: lowercase, `unaccent`, singular,
    collapsed whitespace. It is unique — two rows normalising the same way would
    make resolution non-deterministic.
    """

    __tablename__ = "ingredient"

    id: Mapped[uuid.UUID] = _pk()
    canonical_name: Mapped[str] = mapped_column(String(160))
    normalized_name: Mapped[str] = mapped_column(String(160), unique=True, index=True)

    #: NULL means PROPOSED, and that is not a formality. A machine may propose
    #: this row, never decide it (I1) — so the resolution pass counts only
    #: confirmed ingredients when deriving `allergens_verified` (I3). A file of
    #: proposals nobody re-reads would satisfy the invariant on paper and break
    #: it in substance; this makes the reading load-bearing.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    allergens: Mapped[list[IngredientAllergen]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    aliases: Mapped[list[IngredientAlias]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None


class IngredientAlias(Base):
    """The other spellings of one food.

    `sucre`, `sucre en poudre` and `sucre glace` are one ingredient written three
    ways. Measured on the real catalogue: reaching 300 verified recipes needs
    ~500 distinct strings recognised, which is about 300 actual foods. Without
    this table, the referential grows a duplicate of itself and every allergen
    mapping has to be entered — and kept right — several times.
    """

    __tablename__ = "ingredient_alias"

    id: Mapped[uuid.UUID] = _pk()
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredient.id", ondelete="CASCADE"), index=True
    )
    normalized_name: Mapped[str] = mapped_column(String(160), unique=True, index=True)


class IngredientAllergen(Base):
    """What makes I2 possible at all.

    "crème fraîche", "beurre demi-sel", "parmesan" and "béchamel" all contain
    milk and none contains the substring `lait`. The filter reads THIS table,
    never the text of a recipe.
    """

    __tablename__ = "ingredient_allergen"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredient.id", ondelete="CASCADE"), primary_key=True
    )
    allergen_code: Mapped[AllergenCode] = mapped_column(allergen_enum, primary_key=True)


class IngredientFoodCategory(Base):
    __tablename__ = "ingredient_food_category"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredient.id", ondelete="CASCADE"), primary_key=True
    )
    food_category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_category.id", ondelete="CASCADE"), primary_key=True
    )


class Recipe(Base):
    """A catalogue entry — structured metadata and a link, never the prose (I9).

    `source_url` is unique because it IS the identity of a scraped recipe: it is
    what makes a second campaign update rather than duplicate.
    """

    __tablename__ = "recipe"
    __table_args__ = (
        CheckConstraint(
            "complexity IS NULL OR complexity BETWEEN 1 AND 3", name="ck_recipe_complexity"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    title: Mapped[str] = mapped_column(String(300))
    source_type: Mapped[RecipeSourceType] = mapped_column(recipe_source_enum)
    #: The site. `source_url` is the page. A string matching the key of the YAML
    #: descriptor rather than a foreign key: a `catalog_source` table would
    #: duplicate the descriptor, and the two would drift (§8.2).
    source_code: Mapped[str | None] = mapped_column(String(60), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, unique=True)
    #: Declared BY THE PAGE when it declares one — one source publishes a
    #: licence per recipe. NULL means I9 applies strictly, which is the case of
    #: every blog.
    license: Mapped[str | None] = mapped_column(String(200))
    #: Always equal to `source_url` on the five sources measured in §11.5. Kept
    #: for the case where a site separates the two.
    instructions_url: Mapped[str | None] = mapped_column(Text)

    prep_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    cook_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    #: Derived by formula, never judged by a model (§6.4). NULL until the
    #: formula is settled.
    complexity: Mapped[int | None] = mapped_column(SmallInteger)
    #: When this can be eaten, derived from the rubric the source publishes and
    #: the mapping in `db/dish_types.yaml`. NULL means nobody classified it —
    #: 111 of the 555 verified recipes carry no rubric at all — and the
    #: pre-filter lets NULL through. A quality signal, never a safety one.
    dish_type: Mapped[DishType | None] = mapped_column(dish_type_enum, index=True)
    #: Set when a PERSON decided this dish type, and the reason the pipeline
    #: cannot undo them.
    #:
    #: `catalog dish-types` is idempotent and rewrites `dish_type` for every
    #: recipe from the rubric mapping — so without this, the next run would
    #: erase every manual decision, silently, and the back office would be a
    #: machine for producing work that disappears. `derive` skips any recipe
    #: whose type a human set.
    #:
    #: Which is also why the back office exists: `Tartes, Clafoutis` groups an
    #: onion tart with a strawberry one, so no rubric mapping can be right for
    #: both, and only a person looking at one recipe can tell them apart.
    dish_type_set_by: Mapped[str | None] = mapped_column(String(255))
    dish_type_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: A count, not the steps. Counting is a fact; the text is the author's (I9).
    step_count: Mapped[int | None] = mapped_column(SmallInteger)

    servings: Mapped[int | None] = mapped_column(SmallInteger)
    #: `recipeYield` verbatim. "20 tartelettes" and "4 personnes" are not the
    #: same unit, and scaling portions (§4.4) against the first would be
    #: nonsense. Keeping the raw string is what lets a human tell them apart
    #: later instead of silently trusting a number.
    servings_raw: Mapped[str | None] = mapped_column(String(120))
    #: `recipeCategory` in the source's own words — `Dessert` on one site,
    #: `Terrines` or `Woks` on another. Mapping those onto `food_category` is a
    #: separate job with its own per-source table; keeping the raw strings is
    #: what makes it possible to do it later instead of fetching every page a
    #: second time.
    source_categories: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )

    #: DERIVED (I3): true if and only if EVERY ingredient line resolves. Never
    #: written by the collection pipeline — the resolution pass computes it.
    #: A false here makes the recipe invisible to households with a severe
    #: allergy, and visible to everyone else.
    allergens_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    #: Blogs move and delete pages. Without periodic re-checking the index
    #: drifts silently (§11.3).
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Withdrawn from what may be proposed, and KEPT. NULL — the default —
    #: means offerable.
    #:
    #: Deleting was the alternative and it is wrong twice. `planned_dish`
    #: points here with `ondelete="RESTRICT"`, so weeks already cooked would
    #: block the delete or lose their dish; and a source that goes down may
    #: come back, at which point re-scraping restores the rows rather than
    #: re-discovering them. Set on the whole of `cuisine-libre` in 0013, whose
    #: site now answers 404 — 58 % of the catalogue, which is exactly why it is
    #: marked and not dropped. `catalog.ingest` clears it on a successful
    #: re-scrape, so a source coming back needs no intervention.
    deprecated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="RecipeIngredient.position"
    )
    allergens: Mapped[list[RecipeAllergen]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class RecipeIngredient(Base):
    """One line as the source wrote it, plus what we managed to make of it.

    `raw_text` is ALWAYS kept, resolved or not: it is the only faithful record,
    and the only thing a human can arbitrate against.
    """

    __tablename__ = "recipe_ingredient"
    __table_args__ = (
        # A section header is not an ingredient and must never resolve to one.
        CheckConstraint(
            "NOT (is_section AND ingredient_id IS NOT NULL)",
            name="ck_recipe_ingredient_section_unresolved",
        ),
    )

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    raw_text: Mapped[str] = mapped_column(Text)
    #: Splitting quantity / unit / name is the highest-leverage part of the
    #: pipeline: `c. à soupe d'huile d'olive` and `huile d'olive` are the same
    #: ingredient, and that is a PARSING problem. I4 forbids fixing it with
    #: trigrams — that is exactly where `farine de riz` finds `farine de blé`.
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    unit: Mapped[str | None] = mapped_column(String(40))
    #: `'Pour la pâte sucrée :'` comes marked up as an ingredient and is not
    #: one. Dropping it would lose the ordering; resolving it would be wrong.
    is_section: Mapped[bool] = mapped_column(Boolean, default=False)
    #: NULL = unresolved. Filled by the separate, replayable resolution pass —
    #: a recipe ingested when the referential held 50 entries must gain its
    #: resolutions when it holds 350, without re-scraping (§7.5).
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingredient.id", ondelete="RESTRICT"), index=True
    )


class RecipeAllergen(Base):
    """Derived from the resolved ingredients, never from the text (I2, I3)."""

    __tablename__ = "recipe_allergen"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
    )
    allergen_code: Mapped[AllergenCode] = mapped_column(allergen_enum, primary_key=True)


class RecipeSuitableStage(Base):
    """Which life stages a recipe suits, as SERVED to them (§4.3).

    Defaults to `{young_child, teen_adult}` (§4.5) across the whole scraped
    catalogue, since phase 1 makes no model call. `baby` is never reachable from
    scraping — an assumed limit of the wedge, not a bug.
    """

    __tablename__ = "recipe_suitable_stage"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
    )
    life_stage: Mapped[LifeStage] = mapped_column(life_stage_enum, primary_key=True)


class RecipeFoodCategory(Base):
    __tablename__ = "recipe_food_category"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
    )
    food_category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_category.id", ondelete="CASCADE"), primary_key=True
    )


class IngredientMatchProposal(Base):
    """An approximate match, waiting for a human (I4).

    Keyed by the NORMALISED STRING, not by the ingredient line: one decision
    then resolves every line carrying that text, across every recipe and every
    future campaign. Deciding the same `échalotte` forty times is how a review
    queue stops being reviewed.

    A rejection is as durable as an acceptance — otherwise the next resolution
    pass asks the same question again, forever.
    """

    __tablename__ = "ingredient_match_proposal"

    id: Mapped[uuid.UUID] = _pk()
    normalized_text: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredient.id", ondelete="CASCADE")
    )
    #: Trigram similarity. Recorded to be read back, never to auto-apply above
    #: some threshold: substitute ingredients are named after the food they
    #: replace, so high similarity signals allergenic OPPOSITION as often as
    #: equivalence (I4).
    similarity: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    status: Mapped[ProposalStatus] = mapped_column(
        proposal_status_enum, default=ProposalStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
