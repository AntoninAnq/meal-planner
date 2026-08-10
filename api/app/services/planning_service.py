"""Database <-> planning graph.

The graph itself is pure (`app/workflows/week_plan.py`); every read and write
lives here. This is also the only place that knows the mapping between per-request
aliases and real member ids — the graph and the prompts never see an id (I5).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    DietaryConstraint,
    MealPlan,
    MealSlotConfig,
    Member,
    PlannedDish,
    PlannedDishMember,
)
from app.domain.enums import ConstraintSeverity, DishSource, LifeStage, MealType
from app.domain.planning import ProposedSlot, SlotSpec
from app.domain.prompt_context import MemberInput, build_prompt_context
from app.llm.base import LLMClient
from app.workflows.week_plan import PlanOutcome, PlanRequest, run_plan

#: How far back the anti-repetition signal looks. Soft signal, so the exact
#: value is a tuning knob, not a guarantee.
RECENT_WINDOW_DAYS = 21


@dataclass(frozen=True)
class GuestGroup:
    """Guests are TRANSITORY.

    They never become members: people who eat here twice a year would otherwise
    skew anti-repetition, default portions and stage proposals all year long.
    Their life stage is needed for portions, their allergies exclude the allergen
    from the whole slot, and nothing is stored.
    """

    life_stage: LifeStage
    count: int
    excluded_allergens: tuple[str, ...] = ()
    dislikes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SlotTarget:
    day_of_week: int
    meal_type: MealType


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _members_of(db: Session, household_id: uuid.UUID) -> list[Member]:
    return list(
        db.scalars(
            select(Member).where(Member.household_id == household_id).order_by(Member.created_at)
        )
    )


def _member_inputs(
    db: Session, household_id: uuid.UUID, members: Sequence[Member]
) -> list[MemberInput]:
    """Turn members and their constraints into the I5-safe DTO."""
    constraints = list(
        db.scalars(select(DietaryConstraint).where(DietaryConstraint.household_id == household_id))
    )

    # A constraint with no member applies to the whole household — one concept,
    # one filtering path.
    household_wide = [c for c in constraints if c.member_id is None]

    inputs: list[MemberInput] = []
    for member in members:
        own = [c for c in constraints if c.member_id == member.id]
        applicable = own + household_wide

        inputs.append(
            MemberInput(
                member_id=member.id,
                life_stage=member.life_stage,
                severe_allergens=frozenset(
                    c.allergen_code
                    for c in applicable
                    if c.severity is ConstraintSeverity.SEVERE_ALLERGY and c.allergen_code
                ),
                intolerances=frozenset(
                    c.allergen_code
                    for c in applicable
                    if c.severity is ConstraintSeverity.INTOLERANCE and c.allergen_code
                ),
                aversion_tags=frozenset(
                    c.label or (c.allergen_code or "")
                    for c in applicable
                    if c.severity is ConstraintSeverity.AVERSION
                ),
            )
        )
    return inputs


def enabled_slots(db: Session, household_id: uuid.UUID) -> list[SlotTarget]:
    rows = db.scalars(
        select(MealSlotConfig)
        .where(MealSlotConfig.household_id == household_id, MealSlotConfig.enabled.is_(True))
        .order_by(MealSlotConfig.day_of_week, MealSlotConfig.meal_type)
    )
    return [SlotTarget(row.day_of_week, row.meal_type) for row in rows]


def recent_meals(db: Session, household_id: uuid.UUID, *, before: date) -> list[str]:
    """Implicit history: a past planned dish counts as eaten.

    No scheduled job, and no second source of truth — the read simply looks at
    plans whose date has passed. When explicit history rows exist one day, this
    is where they get unioned in.
    """
    since = before - timedelta(days=RECENT_WINDOW_DAYS)
    rows = db.execute(
        select(MealPlan.week_start, PlannedDish.day_of_week, PlannedDish.free_text_label)
        .join(PlannedDish, PlannedDish.meal_plan_id == MealPlan.id)
        .where(MealPlan.household_id == household_id, MealPlan.week_start >= since)
    ).all()

    labels: list[str] = []
    for week_start, day_of_week, label in rows:
        if label and since <= week_start + timedelta(days=day_of_week) < before:
            labels.append(label)
    return labels


def generate_plan(
    db: Session,
    *,
    household_id: uuid.UUID,
    llm: LLMClient,
    week_start: date,
    targets: Sequence[SlotTarget] | None = None,
    member_ids: Sequence[uuid.UUID] | None = None,
    guests: Sequence[GuestGroup] = (),
    user_constraints: Sequence[str] = (),
) -> tuple[MealPlan, PlanOutcome]:
    """Generate for a whole week, or for a subset of slots.

    A slot-scoped generation UPDATES the week's plan rather than creating a
    parallel one: the plan is a suggestion bank, and regenerating Saturday
    dinner with guests should change Saturday, not fork the week.
    """
    members = _members_of(db, household_id)
    if member_ids is not None:
        keep = set(member_ids)
        members = [member for member in members if member.id in keep]
    if not members:
        raise ValueError("a plan needs at least one member")

    inputs = _member_inputs(db, household_id, members)
    prompt_context, alias_to_member = build_prompt_context(inputs)

    aliases = list(alias_to_member)
    guest_aliases = _guest_aliases(guests)

    slot_targets = list(targets) if targets is not None else enabled_slots(db, household_id)
    spec = [
        SlotSpec(
            day_of_week=target.day_of_week,
            meal_type=target.meal_type,
            eater_aliases=tuple(aliases + guest_aliases),
        )
        for target in slot_targets
    ]
    if not spec:
        raise ValueError("no slot to fill")

    outcome = run_plan(
        PlanRequest(
            spec=spec,
            prompt_context=_with_guests(prompt_context, guests, guest_aliases),
            user_constraints=list(user_constraints),
            recent_meals=recent_meals(db, household_id, before=week_start),
            with_catalogue=False,
        ),
        llm=llm,
    )

    plan = _persist(
        db,
        household_id=household_id,
        week_start=week_start,
        targets=slot_targets,
        proposal=outcome.proposal,
        alias_to_member=alias_to_member,
        generation_input=json.dumps(
            {
                "constraints": list(user_constraints),
                "guests": [
                    {"life_stage": group.life_stage, "count": group.count} for group in guests
                ],
            }
        ),
    )
    return plan, outcome


def _guest_aliases(guests: Sequence[GuestGroup]) -> list[str]:
    aliases: list[str] = []
    for index, group in enumerate(guests, start=1):
        aliases.extend(f"g{index}_{seat}" for seat in range(1, group.count + 1))
    return aliases


def _with_guests(context, guests, guest_aliases):  # type: ignore[no-untyped-def]
    """Add transitory guests to the prompt context.

    A declared guest allergy excludes the allergen from the WHOLE slot — the
    household-scope rule for severe allergies, applied to a single meal.
    Nothing is stored.
    """
    from dataclasses import replace

    from app.domain.prompt_context import MemberContext

    extra: list[MemberContext] = []
    index = 0
    excluded = list(context.household_excluded_allergens)

    for group in guests:
        excluded.extend(group.excluded_allergens)
        for _ in range(group.count):
            extra.append(
                MemberContext(
                    alias=guest_aliases[index],
                    life_stage=group.life_stage,
                    intolerances=(),
                    aversion_tags=tuple(group.dislikes),
                )
            )
            index += 1

    return replace(
        context,
        members=(*context.members, *extra),
        household_excluded_allergens=tuple(sorted(set(excluded))),
    )


def _persist(
    db: Session,
    *,
    household_id: uuid.UUID,
    week_start: date,
    targets: Sequence[SlotTarget],
    proposal: Sequence[ProposedSlot],
    alias_to_member: dict[str, uuid.UUID],
    generation_input: str,
) -> MealPlan:
    plan = db.scalar(
        select(MealPlan).where(
            MealPlan.household_id == household_id, MealPlan.week_start == week_start
        )
    )
    if plan is None:
        plan = MealPlan(household_id=household_id, week_start=week_start)
        db.add(plan)
        db.flush()

    plan.generation_input = generation_input

    # Only the regenerated slots are replaced: a slot-scoped generation must not
    # wipe the six other days that suited the user.
    regenerated = {(target.day_of_week, target.meal_type) for target in targets}
    for dish in list(db.scalars(select(PlannedDish).where(PlannedDish.meal_plan_id == plan.id))):
        if (dish.day_of_week, dish.meal_type) in regenerated:
            db.delete(dish)
    db.flush()

    for slot in proposal:
        for position, proposed in enumerate(slot.dishes):
            dish = PlannedDish(
                meal_plan_id=plan.id,
                day_of_week=slot.day_of_week,
                meal_type=slot.meal_type,
                free_text_label=proposed.label,
                recipe_id=None,  # no catalogue in V0
                source=DishSource.LLM_SUGGESTION,  # invariant I7
                position=position,
            )
            db.add(dish)
            db.flush()

            for alias in proposed.eater_aliases:
                member_id = alias_to_member.get(alias)
                if member_id is None:
                    continue  # a guest: transitory, never stored
                db.add(
                    PlannedDishMember(
                        planned_dish_id=dish.id,
                        member_id=member_id,
                        serving_variant=proposed.serving_variants.get(alias),
                    )
                )

    db.commit()
    return plan


def load_plan(db: Session, household_id: uuid.UUID, week_start: date) -> MealPlan | None:
    return db.scalar(
        select(MealPlan).where(
            MealPlan.household_id == household_id, MealPlan.week_start == week_start
        )
    )


def clear_plan(db: Session, plan: MealPlan) -> None:
    db.execute(delete(PlannedDish).where(PlannedDish.meal_plan_id == plan.id))
    db.commit()
