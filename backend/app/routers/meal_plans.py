"""Meal plan endpoints.

`household_id` appears in no signature — it is derived from the session (I6).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import MealHistory, MealPlan, PlannedDish, PlannedDishMember, Recipe
from app.db.session import get_db
from app.domain.enums import DishSource
from app.llm.base import LLMClient, LLMError
from app.llm.factory import get_llm_client
from app.schemas import (
    DishEaterOut,
    DishOut,
    DishRating,
    DishRegenerate,
    DishReplace,
    GeneratePlanRequest,
    InterpretedConstraint,
    InterpretRequest,
    InterpretResponse,
    MealPlanOut,
    PlanSlotOut,
    SlotGuestsOut,
    SlotScope,
    ViolationOut,
)
from app.services.planning_service import (
    GuestGroup,
    SlotTarget,
    generate_plan,
    load_plan,
    monday_of,
)
from app.workflows.prompts import INTERPRETATION_INSTRUCTIONS, INTERPRETATION_SCHEMA

router = APIRouter(prefix="/meal-plans", tags=["meal-plans"])

DbDep = Annotated[Session, Depends(get_db)]
LLMDep = Annotated[LLMClient, Depends(get_llm_client)]


logger = logging.getLogger(__name__)

#: What the browser is told when the model is unreachable. The exception text
#: names the internal host and port it failed to reach — of no use to a
#: household, and not something an internal address should be printed for.
LLM_UNAVAILABLE = "the meal suggestion service is unavailable, try again in a moment"


def _unavailable(exc: LLMError) -> HTTPException:
    logger.exception("LLM call failed", exc_info=exc)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, LLM_UNAVAILABLE)


def _serialise(db: Session, plan: MealPlan) -> MealPlanOut:
    """Violations come from the plan row, not from an argument.

    They used to travel only in the generation response — but the week view
    loads through GET, so a reload dropped the one thing saying the plan was
    incomplete. Reading them from storage makes the two paths agree by
    construction rather than by discipline.
    """
    dishes = list(
        db.scalars(
            select(PlannedDish)
            .where(PlannedDish.meal_plan_id == plan.id)
            .order_by(PlannedDish.day_of_week, PlannedDish.meal_type, PlannedDish.position)
        )
    )
    assignments = list(
        db.scalars(
            select(PlannedDishMember).where(
                PlannedDishMember.planned_dish_id.in_([dish.id for dish in dishes] or [None])
            )
        )
    )
    by_dish: dict[uuid.UUID, list[PlannedDishMember]] = {}
    for assignment in assignments:
        by_dish.setdefault(assignment.planned_dish_id, []).append(assignment)

    # A catalogue dish carries a `recipe_id` and no label — the title belongs to
    # the recipe, and copying it into the plan would freeze a spelling that a
    # later correction to the catalogue could no longer reach. Read here, in the
    # one place that serialises, rather than denormalised at write time.
    recipe_ids = [dish.recipe_id for dish in dishes if dish.recipe_id]
    titles: dict[uuid.UUID, str] = (
        dict(db.execute(select(Recipe.id, Recipe.title).where(Recipe.id.in_(recipe_ids))).all())
        if recipe_ids
        else {}
    )

    slots: dict[tuple[int, str], PlanSlotOut] = {}
    for dish in dishes:
        key = (dish.day_of_week, dish.meal_type)
        slot = slots.get(key)
        if slot is None:
            slot = PlanSlotOut(
                day_of_week=dish.day_of_week,
                meal_type=dish.meal_type,
                dishes=[],
                guests=[
                    SlotGuestsOut(**group)
                    for group in (plan.slot_guests or {}).get(f"{key[0]}-{key[1]}", [])
                ],
            )
            slots[key] = slot
        slot.dishes.append(
            DishOut(
                id=dish.id,
                label=dish.free_text_label or titles.get(dish.recipe_id),
                recipe_id=dish.recipe_id,
                derived_from_dish_id=dish.derived_from_dish_id,
                eaters=[
                    DishEaterOut(
                        member_id=assignment.member_id,
                        serving_variant=assignment.serving_variant,
                    )
                    for assignment in by_dish.get(dish.id, [])
                ],
            )
        )

    return MealPlanOut(
        id=plan.id,
        week_start=plan.week_start,
        generated_at=plan.generated_at,
        slots=list(slots.values()),
        violations=[ViolationOut(**entry) for entry in plan.violations or ()],
    )


@router.post("/interpret", response_model=InterpretResponse)
def interpret(
    payload: InterpretRequest,
    llm: LLMDep,
    household_id: CurrentHousehold,
) -> InterpretResponse:
    """Free text -> structured constraints, shown to the user before generating.

    The household is not used to interpret anything — it is required so the
    endpoint is not an open, unauthenticated LLM proxy that anyone could point
    arbitrary text at, on our tokens.

    Cheap and short compared with a generation, which is exactly the point: a
    misunderstanding is corrected in one click rather than by rerunning a
    20-30 second arbitration.
    """
    try:
        result = llm.complete_structured(
            instructions=INTERPRETATION_INSTRUCTIONS,
            context=payload.text,
            schema=INTERPRETATION_SCHEMA,
        )
    except LLMError as exc:
        raise _unavailable(exc) from exc

    return InterpretResponse(
        constraints=[
            InterpretedConstraint(**constraint) for constraint in result.data["constraints"]
        ]
    )


@router.post("", response_model=MealPlanOut)
def create_plan(
    payload: GeneratePlanRequest, db: DbDep, llm: LLMDep, household_id: CurrentHousehold
) -> MealPlanOut:
    """One parameterised operation: whole week, or a single slot with guests.

    A slot-scoped generation updates that slot inside the week's plan; it never
    forks a parallel plan and never touches the other days.
    """
    if isinstance(payload.scope, SlotScope):
        week_start = monday_of(payload.scope.day)
        targets: list[SlotTarget] | None = [
            SlotTarget(payload.scope.day.weekday(), payload.scope.meal_type)
        ]
    else:
        week_start = payload.scope.week_start
        targets = None

    try:
        plan, outcome = generate_plan(
            db,
            household_id=household_id,
            llm=llm,
            week_start=week_start,
            targets=targets,
            member_ids=payload.member_ids,
            guests=[
                GuestGroup(
                    life_stage=group.life_stage,
                    count=group.count,
                    excluded_allergens=tuple(group.excluded_allergens),
                    dislikes=tuple(group.dislikes),
                )
                for group in payload.guests
            ],
            user_constraints=payload.constraints,
            language=payload.language,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LLMError as exc:
        raise _unavailable(exc) from exc

    # A plan that never satisfied the envelope is returned WITH what is wrong.
    # Nothing here pretends a rejected plan passed.
    return _serialise(db, plan)


@router.get("", response_model=MealPlanOut | None)
def read_plan(
    db: DbDep, household_id: CurrentHousehold, week_start: Annotated[date, Query()]
) -> MealPlanOut | None:
    """The week view loads from here, not from the generation response.

    That is what makes a lost response survivable: the plan was written before
    the endpoint replied, so a reload recovers it — and the mobile "what's on
    Thursday" view needs this too, since it generates nothing.
    """
    plan = load_plan(db, household_id, week_start)
    return _serialise(db, plan) if plan else None


def _load_dish(db: Session, plan_id: uuid.UUID, dish_id: uuid.UUID, household_id: uuid.UUID):  # type: ignore[no-untyped-def]
    dish = db.get(PlannedDish, dish_id)
    if dish is None or dish.meal_plan_id != plan_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    plan = db.get(MealPlan, plan_id)
    if plan is None or plan.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")
    return dish


@router.get("/{plan_id}/dishes/{dish_id}/alternatives", response_model=list[str])
def alternatives(
    plan_id: uuid.UUID, dish_id: uuid.UUID, db: DbDep, household_id: CurrentHousehold
) -> list[str]:
    """Candidates the pre-filter produced but did not pick. No LLM call.

    Empty in V0: without a catalogue there is no candidate set. The endpoint
    exists so the front is written against the final contract rather than
    against the stub.
    """
    _load_dish(db, plan_id, dish_id, household_id)
    return []


@router.put("/{plan_id}/dishes/{dish_id}", response_model=MealPlanOut)
def replace_dish(
    plan_id: uuid.UUID,
    dish_id: uuid.UUID,
    payload: DishReplace,
    db: DbDep,
    household_id: CurrentHousehold,
) -> MealPlanOut:
    """Immediate write, no draft.

    A plan is not a document: an edit-then-save mechanism would add state, a way
    to lose changes, and a button, for an object the user does not treat as one.
    """
    dish = _load_dish(db, plan_id, dish_id, household_id)
    dish.free_text_label = payload.label
    db.commit()
    return _serialise(db, db.get(MealPlan, plan_id))  # type: ignore[arg-type]


@router.post("/{plan_id}/dishes/{dish_id}/regenerate", response_model=MealPlanOut)
def regenerate_dish(
    plan_id: uuid.UUID,
    dish_id: uuid.UUID,
    payload: DishRegenerate,
    db: DbDep,
    llm: LLMDep,
    household_id: CurrentHousehold,
) -> MealPlanOut:
    """Directed repair — one slot only, never the whole week.

    Regenerating everything would discard the six other days that suited the
    user, for 20-30 seconds of waiting. The stated reason becomes a constraint:
    that is where the value of "why not" lies.
    """
    dish = _load_dish(db, plan_id, dish_id, household_id)
    plan = db.get(MealPlan, plan_id)
    assert plan is not None

    try:
        plan, outcome = generate_plan(
            db,
            household_id=household_id,
            llm=llm,
            week_start=plan.week_start,
            targets=[SlotTarget(dish.day_of_week, dish.meal_type)],
            user_constraints=[payload.reason],
        )
    except LLMError as exc:
        raise _unavailable(exc) from exc

    return _serialise(db, plan)


@router.post("/{plan_id}/dishes/{dish_id}/rating", status_code=status.HTTP_204_NO_CONTENT)
def rate_dish(
    plan_id: uuid.UUID,
    dish_id: uuid.UUID,
    payload: DishRating,
    db: DbDep,
    household_id: CurrentHousehold,
) -> None:
    """Optional, unobtrusive, and nothing depends on it.

    It seeds the appetence score of phase 3+ — which calibrates on history, so
    the earlier it starts the better — and rating IS an implicit confirmation
    that the dish was eaten, which fills `confirmed_at` without ever asking
    anyone to fill in a form.
    """
    dish = _load_dish(db, plan_id, dish_id, household_id)
    plan = db.get(MealPlan, plan_id)
    assert plan is not None

    from datetime import timedelta

    eaten_on = plan.week_start + timedelta(days=dish.day_of_week)
    now = datetime.now(UTC)

    for assignment in db.scalars(
        select(PlannedDishMember).where(PlannedDishMember.planned_dish_id == dish.id)
    ):
        db.add(
            MealHistory(
                household_id=household_id,
                member_id=assignment.member_id,
                eaten_on=eaten_on,
                meal_type=dish.meal_type,
                recipe_id=dish.recipe_id,
                free_text_label=dish.free_text_label,
                source=DishSource.LLM_SUGGESTION,
                rating=payload.value,
                confirmed_at=now,
            )
        )
    db.commit()
