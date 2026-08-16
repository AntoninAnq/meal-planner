"""SQLAlchemy models — phase 0 scope.

Covers households, access, members, constraints, slots, configuration, plans,
history and snacks. The catalogue tables (recipes, ingredients, categories)
arrive in phase 1.

`recipe_id` columns already exist on plan and history rows so the V0 write shape
never changes, but carry no foreign key yet — the phase 1 migration adds the
constraint once `recipe` exists.
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

from app.domain.enums import AllergenCode, ConstraintSeverity, DishSource, LifeStage, MealType


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


class Household(Base):
    __tablename__ = "household"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

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
    # FK added in phase 1. NULL throughout V0.
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # Used by V0, where the model only proposes dish titles.
    free_text_label: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[DishSource] = mapped_column(dish_source_enum)
    position: Mapped[int] = mapped_column(SmallInteger, default=0)
    #: Two preparations sharing a base. Drawn now, always NULL
    #: until the catalogue exists: overlap is not computable without ingredients.
    derived_from_dish_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("planned_dish.id", ondelete="SET NULL")
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
    serving_variant: Mapped[str | None] = mapped_column(String(200))

    dish: Mapped[PlannedDish] = relationship(back_populates="eaters")


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
    # FK added in phase 1.
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
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
    # FK added in phase 1.
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source: Mapped[DishSource] = mapped_column(dish_source_enum)
