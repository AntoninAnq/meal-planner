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
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    DietaryConstraint,
    HouseholdSettings,
    MealPlan,
    MealSlotConfig,
    Member,
    PlannedDish,
    PlannedDishMember,
    Recipe,
    RecipeSuitableStage,
)
from app.domain.enums import ConstraintSeverity, DishSource, LifeStage, MealType
from app.domain.planning import (
    NO_CANDIDATES,
    STAGE_NOT_PLANNED,
    ProposedSlot,
    SlotSpec,
    Violation,
)
from app.domain.prompt_context import MemberInput, build_prompt_context
from app.llm.base import LLMClient
from app.services.catalogue import (
    NOT_A_MEAL,
    HouseholdFilter,
    SqlCatalogue,
    candidate_count,
)
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


def household_filter(
    db: Session, household_id: uuid.UUID, members: Sequence[Member]
) -> HouseholdFilter:
    """Aggregate the household's constraints into pre-filter terms.

    Two rules, and they are not symmetric. A SEVERE allergy excludes the
    allergen for everyone — the scope is the household, because a shared
    kitchen is the unit of contamination (§6.2). An intolerance does not
    exclude anything here: the whole product is that different people eat
    different things, so a recipe one member cannot have is still a candidate
    for the others, and the per-assignment check belongs to re-validation.

    But EITHER makes verification mandatory. The severe/intolerance distinction
    governs the SCOPE of the exclusion, not the RELIABILITY of the data used to
    compute it: on an unverified recipe, `recipe_allergen` is derived from the
    ingredients that resolved, so a missing tag means "we could not read".
    """
    constraints = list(
        db.scalars(select(DietaryConstraint).where(DietaryConstraint.household_id == household_id))
    )
    severe = {
        c.allergen_code
        for c in constraints
        if c.severity is ConstraintSeverity.SEVERE_ALLERGY and c.allergen_code
    }
    declared = {
        c.allergen_code
        for c in constraints
        if c.allergen_code
        and c.severity in (ConstraintSeverity.SEVERE_ALLERGY, ConstraintSeverity.INTOLERANCE)
    }
    return HouseholdFilter(
        excluded_allergens=frozenset(severe),
        require_verified=bool(declared),
        life_stages=frozenset(member.life_stage for member in members),
    )


def stages_without_candidates(db: Session, stages: frozenset[LifeStage]) -> set[LifeStage]:
    """Life stages the catalogue cannot feed at all.

    Measured in phase 2: NONE of the 3 439 scraped recipes carries `baby`, as
    §6.4 warned. Enforcing §4.3 literally would then put an `eater_not_served`
    on every slot of a household with an infant — nine failures a week, for the
    product's own target audience.

    So the stage leaves the grid instead. The system says once what it cannot
    do rather than flagging it nine times, and no safety frontier moves: the
    baby is not served a dish that suits it, it is not served at all. The dish
    derived from the adult's (§4.9, level 3) is what fixes this for real, and
    it is phase 3.

    Computed rather than hardcoded: the day a household writes its own baby
    recipes, this returns an empty set and nothing else changes.
    """
    missing: set[LifeStage] = set()
    for stage in stages:
        exists = db.scalar(
            select(Recipe.id)
            .join(RecipeSuitableStage, RecipeSuitableStage.recipe_id == Recipe.id)
            .where(
                RecipeSuitableStage.life_stage == stage,
                Recipe.dish_type.is_(None) | Recipe.dish_type.not_in(NOT_A_MEAL),
            )
            .limit(1)
        )
        if exists is None:
            missing.add(stage)
    return missing


def _dishes_per_slot(db: Session, household_id: uuid.UUID) -> int:
    """How many dishes a slot may carry, per the household's soft limit.

    Read here to SIZE the candidate set, never to bound the proposal: the limit
    stays a scoring penalty (§4.9), since a household with a baby, a
    lactose-intolerant member and a teenager mechanically needs three dishes.
    """
    settings = db.get(HouseholdSettings, household_id)
    return settings.max_dishes_soft_limit if settings else 2


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
    language: str = "fr",
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

    # A stage the catalogue cannot feed leaves the grid rather than failing
    # every slot. See `stages_without_candidates` for why that is the honest
    # behaviour and not a shortcut.
    unplannable = stages_without_candidates(
        db, frozenset(member.life_stage for member in members)
    )
    unserved = [member for member in members if member.life_stage in unplannable]
    members = [member for member in members if member.life_stage not in unplannable]
    if not members:
        raise ValueError("no member of this household can be served by the catalogue yet")

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

    catalogue = SqlCatalogue(
        db,
        household_id=household_id,
        week_start=week_start,
        household=household_filter(db, household_id, members),
        limit=candidate_count(
            slots=len(spec), dishes_per_slot=_dishes_per_slot(db, household_id)
        ),
    )

    request = PlanRequest(
        spec=spec,
        prompt_context=_with_guests(prompt_context, guests, guest_aliases),
        language=language,
        user_constraints=list(user_constraints),
        recent_meals=recent_meals(db, household_id, before=week_start),
        with_catalogue=True,
    )

    if catalogue.pool_size == 0:
        # No model call: the envelope is empty, so every answer would be
        # rejected, and three attempts would burn minutes to reach a certainty
        # already known here.
        outcome = PlanOutcome(
            proposal=[],
            violations=[
                Violation(
                    NO_CANDIDATES,
                    "no catalogue recipe passes this household's constraints",
                )
            ],
            attempts=0,
            llm_results=[],
        )
    else:
        outcome = run_plan(request, llm=llm, catalogue=catalogue)

    for member in unserved:
        outcome.violations.append(
            Violation(
                STAGE_NOT_PLANNED,
                f"no catalogue recipe suits a {member.life_stage} eater yet",
            )
        )

    plan = _persist(
        db,
        household_id=household_id,
        week_start=week_start,
        targets=slot_targets,
        proposal=outcome.proposal,
        alias_to_member=alias_to_member,
        violations=outcome.violations,
        guests=guests,
        catalogue=catalogue,
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
    violations: Sequence[Violation],
    guests: Sequence[GuestGroup],
    catalogue: SqlCatalogue | None = None,
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
    # Stamped on every generation, not only on the first. The column defaults to
    # the row's creation time, which stops being true the moment a slot is
    # regenerated — and a client that abandoned the wait has nothing else to
    # tell "the plan I was already looking at" from "the one that just landed".
    plan.generated_at = datetime.now(UTC)

    # Only the regenerated slots are replaced: a slot-scoped generation must not
    # wipe the six other days that suited the user.
    regenerated = {(target.day_of_week, target.meal_type) for target in targets}

    # Same rule for the violations: those of the untouched slots still describe
    # what is on the plate there, so only the regenerated ones are replaced.
    kept = [
        entry
        for entry in (plan.violations or [])
        if (entry.get("day_of_week"), entry.get("meal_type")) not in regenerated
    ]
    # Guests are recorded per slot, and only for the slots just generated:
    # regenerating Saturday must not claim the in-laws also came on Tuesday.
    # Anonymous counts, read by nothing but the interface.
    slot_guests = dict(plan.slot_guests or {})
    for target in targets:
        key = f"{target.day_of_week}-{target.meal_type}"
        if guests:
            slot_guests[key] = [
                {"life_stage": group.life_stage, "count": group.count} for group in guests
            ]
        else:
            slot_guests.pop(key, None)
    plan.slot_guests = slot_guests

    plan.violations = kept + [
        {
            "code": violation.code,
            "detail": violation.detail,
            "day_of_week": violation.day_of_week,
            "meal_type": violation.meal_type,
        }
        for violation in violations
    ]

    for dish in list(db.scalars(select(PlannedDish).where(PlannedDish.meal_plan_id == plan.id))):
        if (dish.day_of_week, dish.meal_type) in regenerated:
            db.delete(dish)
    db.flush()

    for slot in proposal:
        for position, proposed in enumerate(slot.dishes):
            # The model emits a HANDLE (`r_012`), never a UUID — see
            # `services/catalogue.py`. Resolving it here is also the last place
            # a handle that never existed can be caught: `validate_proposal`
            # rejects it, but a proposal that exhausted its attempts is
            # persisted WITH its violations, so the row must not be written
            # with neither a recipe nor a label.
            recipe_id = (
                catalogue.resolve(proposed.recipe_id)
                if catalogue is not None and proposed.recipe_id
                else None
            )
            label = proposed.label if recipe_id is None else None
            if recipe_id is None and not (label or "").strip():
                continue

            dish = PlannedDish(
                meal_plan_id=plan.id,
                day_of_week=slot.day_of_week,
                meal_type=slot.meal_type,
                free_text_label=label,
                recipe_id=recipe_id,
                # I7 read the right way round: a catalogue dish was CHOSEN by
                # the model among rows nobody generated, so its source is the
                # catalogue. Only a title the model wrote itself is a
                # suggestion.
                source=DishSource.CATALOG if recipe_id else DishSource.LLM_SUGGESTION,
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
