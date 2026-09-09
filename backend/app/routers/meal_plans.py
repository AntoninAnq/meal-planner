"""Meal plan endpoints.

`household_id` appears in no signature — it is derived from the session (I6).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import (
    Ingredient,
    MealHistory,
    MealPlan,
    Member,
    PlannedDish,
    PlannedDishMember,
    PlannedDishMemberRemoval,
    Recipe,
    RecipeIngredient,
    RecipeSuitableStage,
)
from app.db.session import get_db
from app.domain.enums import DishSource, GenerationKind, LifeStage, MealType
from app.domain.shared_ingredients import pantry, shared_ingredient_links
from app.llm.base import LLMClient, LLMError, SchemaValidationError
from app.llm.factory import get_llm_client
from app.schemas import (
    AlternativeOut,
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
    VariantConfirmation,
    ViolationOut,
)
from app.services.planning_service import (
    GuestGroup,
    Intent,
    SlotTarget,
    catalogue_for,
    generate_plan,
    load_plan,
    monday_of,
)
from app.services.usage import WithinQuota, record
from app.workflows.prompts import INTERPRETATION_INSTRUCTIONS, INTERPRETATION_SCHEMA
from app.workflows.week_plan import PlanOutcome

router = APIRouter(prefix="/meal-plans", tags=["meal-plans"])

DbDep = Annotated[Session, Depends(get_db)]
LLMDep = Annotated[LLMClient, Depends(get_llm_client)]


logger = logging.getLogger(__name__)

#: What the browser is told when the model is unreachable. The exception text
#: names the internal host and port it failed to reach — of no use to a
#: household, and not something an internal address should be printed for.
LLM_UNAVAILABLE = "the meal suggestion service is unavailable, try again in a moment"


def _unavailable(
    db: Session, household_id: uuid.UUID, kind: GenerationKind, exc: LLMError
) -> HTTPException:
    """Bill the failed call, then turn it into a 503.

    A failure is not a free call. Three attempts that never matched the schema
    send three prompts and pay for all of them, which makes an exhausted
    generation the single most expensive outcome the system has — so it is
    logged and it counts against the quota. Skipping it would leave the
    cheapest way to burn an API key uncounted.

    `SchemaValidationError` is the one that knows what it spent. The provider
    being unreachable spent nothing, and the row then says so: zero tokens,
    `succeeded=False` — which is a different fact from "spent nothing because
    it was never called", and the reason `succeeded` is a column of its own.
    """
    logger.exception("LLM call failed", exc_info=exc)
    spent = exc if isinstance(exc, SchemaValidationError) else None
    # The caller may have left a half-written plan behind; the accounting of a
    # call that really happened must not be rolled back with it.
    db.rollback()
    record(
        db,
        household_id=household_id,
        kind=kind,
        input_tokens=spent.input_tokens if spent else 0,
        output_tokens=spent.output_tokens if spent else 0,
        attempts=spent.attempts if spent else 1,
        model_id=spent.model_id if spent else "",
        succeeded=False,
    )
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

    # Who is a baby, and which recipes actually suit that stage. Both are read
    # here so `requires_confirmation` can be DERIVED rather than stored: it is
    # a fact about a member and a recipe, and the day the catalogue holds real
    # baby recipes it must stop being true on its own.
    babies = {
        member_id
        for member_id in db.scalars(
            select(Member.id).where(
                Member.household_id == plan.household_id, Member.life_stage == LifeStage.BABY
            )
        )
    }
    suits_baby: set[uuid.UUID] = set()
    removals: dict[tuple[uuid.UUID, uuid.UUID], list[str]] = {}
    if babies:
        suits_baby = set(
            db.scalars(
                select(RecipeSuitableStage.recipe_id).where(
                    RecipeSuitableStage.life_stage == LifeStage.BABY
                )
            )
        )
        for dish_id, member_id, name in db.execute(
            select(
                PlannedDishMemberRemoval.planned_dish_id,
                PlannedDishMemberRemoval.member_id,
                Ingredient.canonical_name,
            )
            .join(Ingredient, Ingredient.id == PlannedDishMemberRemoval.ingredient_id)
            .where(
                PlannedDishMemberRemoval.planned_dish_id.in_(
                    [dish.id for dish in dishes] or [None]
                )
            )
        ).all():
            removals.setdefault((dish_id, member_id), []).append(name)

    # A catalogue dish carries a `recipe_id` and no label — the title belongs to
    # the recipe, and copying it into the plan would freeze a spelling that a
    # later correction to the catalogue could no longer reach. Read here, in the
    # one place that serialises, rather than denormalised at write time.
    recipe_ids = [dish.recipe_id for dish in dishes if dish.recipe_id]
    meta: dict[uuid.UUID, RecipeMeta] = {}
    if recipe_ids:
        for recipe_id, title, prep, cook, complexity, source_url in db.execute(
            select(
                Recipe.id,
                Recipe.title,
                Recipe.prep_minutes,
                Recipe.cook_minutes,
                Recipe.complexity,
                Recipe.source_url,
            ).where(Recipe.id.in_(recipe_ids))
        ).all():
            minutes = (prep or 0) + (cook or 0) if (prep is not None or cook is not None) else None
            meta[recipe_id] = RecipeMeta(title, minutes, complexity, source_url)

    shares_with = _shared_ingredient_links(db, dishes)

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
        about = meta.get(dish.recipe_id) if dish.recipe_id else None
        slot.dishes.append(
            DishOut(
                id=dish.id,
                label=dish.free_text_label or (about.title if about else None),
                recipe_id=dish.recipe_id,
                source=dish.source,
                minutes=about.minutes if about else None,
                complexity=about.complexity if about else None,
                source_url=about.source_url if about else None,
                shares_ingredients_with=shares_with.get(dish.id),
                eaters=[
                    DishEaterOut(
                        member_id=assignment.member_id,
                        serving_variant=assignment.serving_variant,
                        requires_confirmation=(
                            assignment.member_id in babies
                            and dish.recipe_id not in suits_baby
                        ),
                        variant_confirmed_at=assignment.variant_confirmed_at,
                        removals=sorted(
                            removals.get((dish.id, assignment.member_id), [])
                        ),
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
    db: DbDep,
    llm: LLMDep,
    household_id: WithinQuota,
) -> InterpretResponse:
    """Free text -> structured constraints, shown to the user before generating.

    The household is not used to interpret anything — it is required so the
    endpoint is not an open, unauthenticated LLM proxy that anyone could point
    arbitrary text at, on our tokens.

    Cheap and short compared with a generation, which is exactly the point: a
    misunderstanding is corrected in one click rather than by rerunning a
    20-30 second arbitration.

    Cheap, and still under the quota. Roughly a tenth of a week's cost — which
    is a reason to set the limit generously, not a reason to leave the endpoint
    unmetered: it is reachable in a loop exactly as easily as the expensive one.
    """
    try:
        result = llm.complete_structured(
            instructions=INTERPRETATION_INSTRUCTIONS,
            context=payload.text,
            schema=INTERPRETATION_SCHEMA,
        )
    except LLMError as exc:
        raise _unavailable(db, household_id, GenerationKind.INTERPRET, exc) from exc

    record(
        db,
        household_id=household_id,
        kind=GenerationKind.INTERPRET,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        attempts=result.attempts,
        model_id=result.model_id,
    )

    return InterpretResponse(
        constraints=[
            InterpretedConstraint(**constraint) for constraint in result.data["constraints"]
        ]
    )


@router.post("", response_model=MealPlanOut)
def create_plan(
    payload: GeneratePlanRequest, db: DbDep, llm: LLMDep, household_id: WithinQuota
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
        kind = GenerationKind.SLOT
    else:
        week_start = payload.scope.week_start
        targets = None
        kind = GenerationKind.WEEK

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
            # Converted HERE, explicitly. `InterpretedConstraint` and `Intent`
            # carry the same three fields and are different types, so passing
            # the first where the second is expected type-checks nowhere and
            # fails silently: `generate_plan` fell through to its bare-string
            # branch and turned every constraint into `kind="other"`.
            #
            # Measured cost: a full day of work on `skip_slot`, `time_budget`
            # and `repeat` that was never once applied through the interface,
            # while every test passed — the tests built `Intent` directly.
            user_constraints=[
                Intent(kind=entry.kind, label=entry.label, detail=entry.detail)
                for entry in payload.constraints
            ],
            language=payload.language,
        )
    except ValueError as exc:
        # Not billed: all three of these are refused before a prompt is built.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LLMError as exc:
        raise _unavailable(db, household_id, kind, exc) from exc

    _bill(db, household_id, kind, outcome)

    # A plan that never satisfied the envelope is returned WITH what is wrong.
    # Nothing here pretends a rejected plan passed.
    return _serialise(db, plan)


def _bill(
    db: Session, household_id: uuid.UUID, kind: GenerationKind, outcome: PlanOutcome
) -> None:
    """Record what a completed generation consumed, over every attempt.

    A rejected plan still went to the model and still counts — the envelope
    loop is where the tokens go, not where they stop mattering.
    """
    record(
        db,
        household_id=household_id,
        kind=kind,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        attempts=outcome.attempts,
        # What the provider says it ran. The generation may have taken several
        # attempts; they all go to the same model, so the last one names it.
        model_id=outcome.llm_results[-1].model_id if outcome.llm_results else "",
    )


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


def _shared_ingredient_links(
    db: Session, dishes: list[PlannedDish]
) -> dict[uuid.UUID, uuid.UUID]:
    """Which meals of this week are built on the same things.

    Read here rather than stored: it is a pure function of the plan's recipes
    and the catalogue, so a correction to either reaches every plan already
    written, and no migration is needed to light it up on the weeks that exist.

    Two queries, both cheap: the pantry census is a grouped scan of ~29 000
    ingredient lines, and the second reads only the recipes on this plan.
    """
    by_recipe: dict[uuid.UUID, uuid.UUID] = {
        dish.id: dish.recipe_id for dish in dishes if dish.recipe_id
    }
    if len(by_recipe) < 2:
        return {}

    catalogue_size = db.scalar(select(func.count()).select_from(Recipe)) or 0
    census = {
        ingredient_id: count
        for ingredient_id, count in db.execute(
            select(
                RecipeIngredient.ingredient_id,
                func.count(func.distinct(RecipeIngredient.recipe_id)),
            )
            .where(RecipeIngredient.ingredient_id.is_not(None))
            .group_by(RecipeIngredient.ingredient_id)
        ).all()
    }
    cupboard = pantry(census, catalogue_size)

    lines: dict[uuid.UUID, set[uuid.UUID]] = {}
    for recipe_id, ingredient_id in db.execute(
        select(RecipeIngredient.recipe_id, RecipeIngredient.ingredient_id).where(
            RecipeIngredient.recipe_id.in_(set(by_recipe.values())),
            RecipeIngredient.ingredient_id.is_not(None),
        )
    ).all():
        if ingredient_id not in cupboard:
            lines.setdefault(recipe_id, set()).add(ingredient_id)

    # Chronological, because the marker names the meal already cooked. Ties
    # inside a day fall back on the meal name, which orders lunch before
    # dinner — the order they are eaten in.
    order = sorted(dishes, key=lambda dish: (dish.day_of_week, dish.meal_type != MealType.LUNCH))
    ingredients = {
        dish.id: frozenset(lines.get(dish.recipe_id, set())) if dish.recipe_id else frozenset()
        for dish in order
    }
    return shared_ingredient_links([dish.id for dish in order], ingredients)


class RecipeMeta(NamedTuple):
    """What the plan does not store, read at serialisation time.

    A catalogue dish carries a `recipe_id` and no copy of the recipe: the title,
    the effort and the address all belong to the catalogue row, so a correction
    made there reaches every plan that already points at it.
    """

    title: str
    minutes: int | None
    complexity: int | None
    source_url: str


def _load_dish(db: Session, plan_id: uuid.UUID, dish_id: uuid.UUID, household_id: uuid.UUID):  # type: ignore[no-untyped-def]
    dish = db.get(PlannedDish, dish_id)
    if dish is None or dish.meal_plan_id != plan_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    plan = db.get(MealPlan, plan_id)
    if plan is None or plan.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")
    return dish


#: How many alternatives a refusal offers. `UX-V0.md` §6 says "en montrer
#: trois autres": enough to choose from, few enough to read at a glance.
ALTERNATIVES_SHOWN = 3


@router.get(
    "/{plan_id}/dishes/{dish_id}/alternatives", response_model=list[AlternativeOut]
)
def alternatives(
    plan_id: uuid.UUID, dish_id: uuid.UUID, db: DbDep, household_id: CurrentHousehold
) -> list[AlternativeOut]:
    """Candidates the pre-filter produced but did not pick. No LLM call.

    The cheapest mechanism in the product and, per `UX-V0.md` §6, the most
    frequently useful one: "not that one, show me something else" needs no
    negotiation, just the list the model already had.

    Nothing was stored to make this possible. The ranking is seeded on the
    household and the week, so rebuilding it here reproduces exactly what the
    generation was shown — which is why the reserve costs neither tokens nor a
    table.
    """
    # Called for its checks, not its value: it is what turns another
    # household's dish id into a 404.
    _load_dish(db, plan_id, dish_id, household_id)
    plan = db.get(MealPlan, plan_id)
    assert plan is not None

    # Everything already on the plate this week is excluded, not just the dish
    # being refused: offering Thursday's gratin as an alternative to Tuesday's
    # is an answer nobody wants.
    already = {
        row
        for row in db.scalars(
            select(PlannedDish.recipe_id).where(
                PlannedDish.meal_plan_id == plan.id, PlannedDish.recipe_id.is_not(None)
            )
        )
    }
    catalogue = catalogue_for(db, household_id=household_id, week_start=plan.week_start)
    offered = catalogue.alternatives(exclude=already, limit=ALTERNATIVES_SHOWN)

    return [
        AlternativeOut(
            recipe_id=candidate.recipe_id,
            title=candidate.title,
            minutes=candidate.minutes,
            complexity=candidate.complexity,
            ingredients=candidate.ingredients,
            source_url=candidate.source_url or None,
        )
        for candidate in offered
    ]


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
    if (payload.recipe_id is None) == (payload.label is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "give either a recipe_id or a label, not both and not neither",
        )

    dish = _load_dish(db, plan_id, dish_id, household_id)

    if payload.recipe_id is not None:
        recipe = db.get(Recipe, payload.recipe_id)
        if recipe is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
        dish.recipe_id = recipe.id
        dish.free_text_label = None
        dish.source = DishSource.CATALOG
    else:
        # A title someone typed. `recipe_id` is cleared: the dish is no longer
        # the catalogue's, and keeping the old reference would make the plan
        # claim a provenance it lost.
        dish.recipe_id = None
        dish.free_text_label = payload.label
        dish.source = DishSource.USER

    db.commit()
    return _serialise(db, db.get(MealPlan, plan_id))  # type: ignore[arg-type]


@router.post("/{plan_id}/dishes/{dish_id}/regenerate", response_model=MealPlanOut)
def regenerate_dish(
    plan_id: uuid.UUID,
    dish_id: uuid.UUID,
    payload: DishRegenerate,
    db: DbDep,
    llm: LLMDep,
    household_id: WithinQuota,
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
            # The refused dish leaves the pool. Without this the model may
            # answer with the very thing someone just rejected — the one reply
            # that makes directed repair worthless.
            exclude_recipe_ids=[dish.recipe_id] if dish.recipe_id else [],
        )
    except LLMError as exc:
        raise _unavailable(db, household_id, GenerationKind.REGENERATE, exc) from exc

    _bill(db, household_id, GenerationKind.REGENERATE, outcome)

    return _serialise(db, plan)


@router.post(
    "/{plan_id}/dishes/{dish_id}/variant-confirmation",
    status_code=status.HTTP_204_NO_CONTENT,
)
def confirm_variant(
    plan_id: uuid.UUID,
    dish_id: uuid.UUID,
    payload: VariantConfirmation,
    db: DbDep,
    household_id: CurrentHousehold,
) -> None:
    """A parent taking responsibility for one baby plate (§4.9).

    This is the only thing standing between "the model wrote a serving
    instruction" and "a 16-month-old is served an adult dish". I1 forbids a
    LLM deciding safety, not a human — but the difference has to be recorded
    where the code can read it, and this endpoint is that record.

    Per dish and per member, deliberately. What is confirmed is that THIS
    texture suits THIS child; a week-wide approval would be the system deciding
    again under someone's name.

    Reversible: `confirmed: false` clears it. A parent who confirmed too
    quickly must be able to take it back, and a confirmation that cannot be
    withdrawn teaches people not to give it.
    """
    _load_dish(db, plan_id, dish_id, household_id)

    # Scoped to the household, so one household cannot confirm another's plate.
    member = db.get(Member, payload.member_id)
    if member is None or member.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")

    assignment = db.get(PlannedDishMember, (dish_id, payload.member_id))
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this member does not eat this dish")

    # Refused rather than ignored on a dish carrying no variant: confirming
    # nothing would store a parent's approval of a plate that was never
    # described to them.
    if payload.confirmed and not assignment.serving_variant:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "there is no serving variant to confirm on this dish",
        )

    assignment.variant_confirmed_at = datetime.now(UTC) if payload.confirmed else None
    db.commit()


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


def _parse_slot(slot: str) -> tuple[int, MealType]:
    """`"5-dinner"` → `(5, MealType.DINNER)`, the same key the grid uses.

    Its own function so a malformed key is one `ValueError` the caller turns
    into a 422, rather than an `IndexError` or a bare `KeyError` 500.
    """
    day, _, meal = slot.partition("-")
    if not day.isdigit() or not (0 <= int(day) <= 6):
        raise ValueError("slot day must be 0..6")
    try:
        return int(day), MealType(meal)
    except ValueError:
        raise ValueError("slot meal must be 'lunch' or 'dinner'") from None


@router.delete("/{plan_id}/slots/{slot}", response_model=MealPlanOut)
def clear_slot(
    plan_id: uuid.UUID,
    slot: str,
    db: DbDep,
    household_id: CurrentHousehold,
) -> MealPlanOut:
    """Empty one slot — every dish on it — without touching the rest of the week.

    A household plans Saturday dinner as usual, then invites people over: the
    habitual meal has to give way. Regenerating the week to drop one meal would
    discard the six days that were fine (`UX-V0.md` §6), so the slot is cleared
    in place and simply reads as empty afterwards — a plan is a bank of
    suggestions, not a commitment (§1), and an empty slot is a valid state.

    The invitation for this slot, if there is one, is left alone: it lives
    beside the plan and outlives any one generation of the meal.
    """
    plan = db.get(MealPlan, plan_id)
    if plan is None or plan.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")

    try:
        day_of_week, meal_type = _parse_slot(slot)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    for dish in db.scalars(
        select(PlannedDish).where(
            PlannedDish.meal_plan_id == plan.id,
            PlannedDish.day_of_week == day_of_week,
            PlannedDish.meal_type == meal_type,
        )
    ):
        db.delete(dish)

    # The display cache and this slot's own violations describe dishes that no
    # longer exist. A plan-level violation carries no slot key and stays put.
    key = f"{day_of_week}-{meal_type}"
    plan.slot_guests = {k: v for k, v in (plan.slot_guests or {}).items() if k != key}
    plan.violations = [
        entry
        for entry in (plan.violations or [])
        if (entry.get("day_of_week"), entry.get("meal_type")) != (day_of_week, meal_type)
    ]
    db.commit()
    return _serialise(db, db.get(MealPlan, plan_id))  # type: ignore[arg-type]
