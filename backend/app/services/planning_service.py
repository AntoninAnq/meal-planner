"""Database <-> planning graph.

The graph itself is pure (`app/workflows/week_plan.py`); every read and write
lives here. This is also the only place that knows the mapping between per-request
aliases and real member ids — the graph and the prompts never see an id (I5).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    DietaryConstraint,
    FoodCategory,
    HouseholdSettings,
    Ingredient,
    MealPlan,
    MealSlotConfig,
    Member,
    PlannedDish,
    PlannedDishMember,
    PlannedDishMemberRemoval,
    Recipe,
    RecipeAllergen,
    RecipeFoodCategory,
    RecipeIngredient,
    RecipeSuitableStage,
)
from app.domain.days import parse_days, slots_to_skip
from app.domain.enums import ConstraintSeverity, DishSource, LifeStage, MealType
from app.domain.planning import (
    ALLERGEN_ON_PLANNED_DISH,
    NO_CANDIDATES,
    STAGE_NOT_PLANNED,
    UNVERIFIED_ON_PLANNED_DISH,
    EaterSafety,
    ProposedSlot,
    SlotSpec,
    Violation,
)
from app.domain.prompt_context import MemberInput, PromptContext, build_prompt_context
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


#: The categories worth rotating on. Deliberately NOT every category the
#: derivation writes: `fat_oil`, `condiment` and `herb_spice` appear in more
#: than half the catalogue, and a signal that fires everywhere carries nothing —
#: the same trap the overlap signal fell into. `dairy` and `nuts_seeds` are out
#: for the same reason; `fruit` because it is not a rotation axis for dinner.
ROTATION_CATEGORIES = (
    "red_meat", "white_meat", "charcuterie", "fish", "seafood", "legumes_secs",
    "egg", "cheese", "green_vegetable", "root_vegetable", "vegetable", "cereal",
)

#: How far back to look. Beyond this, "not for a long time" and "never" are the
#: same statement to a household, and reporting 140 days would only make the
#: line longer.
ROTATION_WINDOW_DAYS = 60


def render_rotation(last_seen: Mapping[str, date], *, before: date) -> list[str]:
    """Format the gaps. Pure, so the wording is testable without a database.

    Silent when nothing has been eaten: twelve lines of "jamais" is not a
    signal, it is noise in a prompt that already carries sixty candidates, and
    "you have never had fish" describes an empty history rather than advising
    anything. The block reappears by itself after the first week.
    """
    if not last_seen:
        return []

    lines: list[str] = []
    for code in ROTATION_CATEGORIES:
        eaten = last_seen.get(code)
        if eaten is None:
            lines.append(f"{code}: jamais")
        else:
            days = (before - eaten).days
            lines.append(f"{code}: {days} jour{'s' if days > 1 else ''}")
    return lines


def rotation_signal(db: Session, household_id: uuid.UUID, *, before: date) -> list[str]:
    """Days since each food category was last on the table.

    The fourth soft signal of §6.2, and the one that was deferred. It was
    deferred on a condition I set and got wrong twice: it counted desserts in
    the denominator, and it read "contains meat" where the signal needs "is
    made of". Measured on the 196 verified mains and starters, 83 % carry a
    vegetable and 72 % a protein once eggs and cheese are counted — the
    composition was there all along; nothing derived it.

    Soft by construction (§6.3): it is passed to the prompt as context and
    filters nothing. "Some pulses would be good this week" must yield to a
    teenager who hates lentils.
    """
    since = before - timedelta(days=ROTATION_WINDOW_DAYS)
    rows = db.execute(
        select(MealPlan.week_start, PlannedDish.day_of_week, FoodCategory.code)
        .join(PlannedDish, PlannedDish.meal_plan_id == MealPlan.id)
        .join(RecipeFoodCategory, RecipeFoodCategory.recipe_id == PlannedDish.recipe_id)
        .join(FoodCategory, FoodCategory.id == RecipeFoodCategory.food_category_id)
        .where(MealPlan.household_id == household_id, MealPlan.week_start >= since)
    ).all()

    last_seen: dict[str, date] = {}
    for week_start, day_of_week, code in rows:
        eaten = week_start + timedelta(days=day_of_week)
        if eaten >= before:
            continue  # planned, not yet eaten
        if code not in last_seen or eaten > last_seen[code]:
            last_seen[code] = eaten

    return render_rotation(last_seen, before=before)


def catalogue_for(
    db: Session,
    *,
    household_id: uuid.UUID,
    week_start: date,
    exclude: frozenset[uuid.UUID] = frozenset(),
) -> SqlCatalogue:
    """Rebuild the exact pre-filter a generation used.

    Same household, same week, same seed — so the ranking comes back
    identical and `GET …/alternatives` offers candidates the model really was
    shown. This is what makes storing the candidate set unnecessary.
    """
    members = _members_of(db, household_id)
    unplannable = stages_without_candidates(
        db, frozenset(member.life_stage for member in members)
    )
    served = [member for member in members if member.life_stage not in unplannable]
    slots = enabled_slots(db, household_id)
    inputs = _member_inputs(db, household_id, served or members)
    return SqlCatalogue(
        db,
        household_id=household_id,
        week_start=week_start,
        household=household_filter(db, household_id, served or members),
        limit=candidate_count(
            slots=max(len(slots), 1), dishes_per_slot=_dishes_per_slot(db, household_id)
        ),
        exclude=exclude,
        # The same preference, or rebuilding the ranking here would produce a
        # different order from the one the generation used — and the reserve is
        # recomputed rather than stored precisely because the two must match.
        prefer_free_of=_excluded_allergens(inputs),
        # For the same reason, and it matters more here than anywhere: this is
        # what feeds "not that one, show me something else". Offering back the
        # ingredient someone never eats is the one answer that makes the
        # feature worse than nothing.
        disliked_ingredients=_dislikes(inputs),
    )


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
    # `baby` is left OUT of the stage filter, and it has to be. The filter keeps
    # recipes suiting at least one stage present, and zero of the 3 439 recipes
    # carries `baby` — so a household whose only eater is an infant matched
    # nothing at all and got `no_candidates` on every slot. That is the old
    # "the stage leaves the grid" behaviour resurfacing one layer down.
    #
    # §4.9 feeds that stage by ADAPTING an adult dish, so the recipes it needs
    # are precisely the ones this filter would have to drop. Harmless for a
    # mixed household — the filter is a disjunction, and the adults already
    # keep the pool open — and decisive for a household of one baby.
    plannable = frozenset(
        member.life_stage for member in members if member.life_stage is not LifeStage.BABY
    )
    return HouseholdFilter(
        excluded_allergens=frozenset(severe),
        require_verified=bool(declared),
        life_stages=plannable,
    )


def stages_without_candidates(db: Session, stages: frozenset[LifeStage]) -> set[LifeStage]:
    """Life stages the catalogue cannot feed at all.

    Measured in phase 2: NONE of the 3 439 scraped recipes carries `baby`, as
    §6.4 warned. Enforcing §4.3 literally would then put an `eater_not_served`
    on every slot of a household with an infant — nine failures a week, for the
    product's own target audience.

    So the stage left the grid instead. The system said once what it could not
    do rather than flagging it nine times, and no safety frontier moved: the
    baby was not served a dish that suits it, it was not served at all.

    **`baby` no longer leaves the grid.** §4.9 now lets a serving variant open
    the assignment for that stage alone, confirmed by the parent — so a
    household with an infant is served, and the absence of baby recipes is
    answered by adapting an adult dish rather than by giving up. This function
    keeps the mechanism for any FUTURE stage the catalogue cannot feed; it is
    simply no longer the answer for this one.

    Computed rather than hardcoded, and that is what makes the exemption safe:
    the day the catalogue holds real baby recipes, `baby` stops being exempt on
    its own and the ordinary rule applies again.
    """
    missing: set[LifeStage] = set()
    for stage in stages:
        if stage is LifeStage.BABY:
            continue
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
    # A catalogue dish carries a `recipe_id` and no label, so reading
    # `free_text_label` alone made the anti-repetition signal go silent the day
    # the catalogue was branched — the plans were full and the block was empty.
    rows = db.execute(
        select(
            MealPlan.week_start,
            PlannedDish.day_of_week,
            PlannedDish.free_text_label,
            Recipe.title,
        )
        .join(PlannedDish, PlannedDish.meal_plan_id == MealPlan.id)
        .outerjoin(Recipe, Recipe.id == PlannedDish.recipe_id)
        .where(MealPlan.household_id == household_id, MealPlan.week_start >= since)
    ).all()

    labels: list[str] = []
    for week_start, day_of_week, label, title in rows:
        eaten = label or title
        if eaten and since <= week_start + timedelta(days=day_of_week) < before:
            labels.append(eaten)
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
    user_constraints: Sequence[Intent | str] = (),
    language: str = "fr",
    exclude_recipe_ids: Sequence[uuid.UUID] = (),
) -> tuple[MealPlan, PlanOutcome]:
    """Generate for a whole week, or for a subset of slots.

    A slot-scoped generation UPDATES the week's plan rather than creating a
    parallel one: the plan is a suggestion bank, and regenerating Saturday
    dinner with guests should change Saturday, not fork the week.
    """
    # A bare string still works — the slot-level repair sends one reason and
    # has no interpretation step behind it.
    intents = [
        entry if isinstance(entry, Intent) else Intent(kind="other", label=str(entry))
        for entry in user_constraints
    ]

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
    # A slot the household said not to plan is REMOVED, never described to the
    # model. It used to travel as prose — "absence mardi" in a block of text —
    # and a dinner was planned for Tuesday anyway. Nothing here needs a model:
    # a day named is a day known, and §6.3 puts that on the deterministic side.
    spec = _without_skipped(spec, intents, language)
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
        exclude=frozenset(exclude_recipe_ids),
        # Ranked first, never filtered out (§6.2 keeps an intolerance at member
        # scope). What changes is what the model sees at the top of a list it
        # was measured walking in order.
        prefer_free_of=_excluded_allergens(inputs),
        wanted_ingredients=_named_ingredients(intents, WANTED_KINDS),
        unwanted_ingredients=_named_ingredients(intents, UNWANTED_KINDS),
        # Standing aversions, removed from the pool rather than described to
        # the model — see `SqlCatalogue._dropped_for_dislikes`.
        disliked_ingredients=_dislikes(inputs),
        # "Peu de temps cette semaine" favours the quick dishes. Prose alone
        # moved nothing: measured at 9 slots out of 9 on the highest complexity
        # while 14 quick candidates sat in the same list. A fraction rather
        # than a flag, so that a constraint naming only some days still leaves
        # the model a long dish for the Sunday — see `quick_share`.
        quick_share=quick_share(spec, intents, language),
    )

    request = PlanRequest(
        safety=_eater_safety(db, catalogue, inputs, alias_to_member),
        rotation=rotation_signal(db, household_id, before=week_start),
        spec=spec,
        prompt_context=_with_guests(
            _without_enforced_dislikes(prompt_context, catalogue.enforced_dislikes),
            guests,
            guest_aliases,
        ),
        language=language,
        user_constraints=[intent.phrase() for intent in intents],
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
                "constraints": [intent.phrase() for intent in intents],
                "guests": [
                    {"life_stage": group.life_stage, "count": group.count} for group in guests
                ],
            }
        ),
    )
    return plan, outcome


#: Which interpreted `kind` the pre-filter can act on, and how.
#:
#: This comment used to end "the rest — `time_budget`, `skip_slot`, `other` —
#: stay prose for the model: they are about the SHAPE of the week, which is not
#: a property of a recipe." That was half right and cost a whole week.
#:
#: `skip_slot` is not about a recipe, true — it is about the GRID, which is
#: ours to change, and it is now applied by removing the slot. `time_budget` is
#: not about one recipe either, but it is about a property every recipe has:
#: measured effort. Both were handed to the model as sentences and both were
#: ignored — 9 slots out of 9 at the highest complexity when the pool held 14
#: quick dishes, and a dinner planned for a Tuesday the household had said it
#: would be away.
#:
#: `other` genuinely stays prose. It is the kind that means "we could not
#: classify this", and inventing a mechanism for it would be inventing intent.
WANTED_KINDS = ("leftover", "prefer")
UNWANTED_KINDS = ("avoid",)
SKIP_KINDS = ("skip_slot",)
TIME_KINDS = ("time_budget",)


def quick_share(
    spec: Sequence[SlotSpec], intents: Sequence[Intent], language: str
) -> float:
    """How much of the candidate list should be quick, between 0 and 1.

    Three cases, and the middle one is why this is a fraction rather than a flag.

    No time constraint at all -> `0`. Nothing is favoured.

    A constraint naming NO day -> `1`. "J'aurai peu de temps cette semaine" is
    about every slot, so every candidate may as well be quick. Measured on the
    real catalogue: 60 of the 60 shown, against 23 without.

    A constraint naming SOME days -> the share of slots those days cover. "Je
    rentre tard du mardi au vendredi, le week-end j'ai le temps" is a week with
    a shape, and a list of 60 quick dishes cannot produce one — there is no long
    dish left for the Sunday. Measured before this existed: `founder`, whose
    intent says exactly that, scored 2.18 on weeknights against 2.20 at
    weekends. The same flat number.

    Using the slot share directly keeps both sides comfortably stocked: 4 named
    slots out of 9 gives 27 quick candidates and 33 others, where the week needs
    4 and 5.
    """
    phrases = [intent.phrase() for intent in intents if intent.kind in TIME_KINDS]
    if not phrases or not spec:
        return 0.0

    days: set[int] = set()
    for phrase in phrases:
        days |= parse_days(phrase, language)
    if not days:
        return 1.0

    named = sum(1 for slot in spec if slot.day_of_week in days)
    # A named day with no enabled slot says nothing usable; treating it as 0
    # would silently drop a constraint the household did state.
    return named / len(spec) if named else 1.0


def _without_skipped(
    spec: Sequence[SlotSpec], intents: Sequence[Intent], language: str
) -> list[SlotSpec]:
    """Drop the slots a `skip_slot` constraint names.

    Two refusals, both because the cost is asymmetric. A slot planned that the
    household skips costs one wasted suggestion; a slot silently cancelled
    costs a meal they expected — so a phrase naming no day cancels nothing, and
    a reading that would empty the week is dropped whole.

    That second guard is not theoretical: `parse_days` reads any day it finds,
    so a household writing about every day of the week would otherwise get an
    empty plan and the bare "no slot to fill" error.
    """
    phrases = [intent.phrase() for intent in intents if intent.kind in SKIP_KINDS]
    if not phrases:
        return list(spec)

    skipped = slots_to_skip(phrases, language)
    if not skipped:
        return list(spec)

    kept = [
        slot
        for slot in spec
        if (slot.day_of_week, None) not in skipped
        and (slot.day_of_week, slot.meal_type) not in skipped
    ]
    return kept or list(spec)


@dataclass(frozen=True)
class Intent:
    """A confirmed constraint, as the interpretation structured it.

    Kept structured all the way here rather than flattened to a label. The
    front used to send `"il reste du jambon: jambon"` and the model was asked
    to find, among sixty candidates, the ones containing ham — a search §6.3
    puts on the deterministic side.
    """

    kind: str
    label: str
    detail: str | None = None

    def phrase(self) -> str:
        return f"{self.label}: {self.detail}" if self.detail else self.label


def _named_ingredients(intents: Sequence[Intent], kinds: Sequence[str]) -> frozenset[str]:
    """The ingredient a constraint names, when it names one.

    `detail` is where the interpretation puts the specific value — an
    ingredient, a day, a duration. Only the ones the referential recognises
    will match anything, and a word it does not know matches nothing rather
    than matching wrongly.
    """
    return frozenset(
        intent.detail for intent in intents if intent.kind in kinds and intent.detail
    )


def _dislikes(inputs: Sequence[MemberInput]) -> frozenset[str]:
    """Every standing aversion at the table, whoever holds it.

    Household scope, and that is the point rather than an approximation. §2.3
    says the objective is to cook ONCE: a dish only one person can eat costs
    the whole benefit, so a recipe built on something one member never eats is
    not a candidate for that household's dinner — it is a candidate for a
    second dish nobody asked for.
    """
    return frozenset(tag for entry in inputs for tag in entry.aversion_tags if tag)


def _without_enforced_dislikes(
    context: PromptContext, enforced: frozenset[str]
) -> PromptContext:
    """Drop from the prompt the aversions the pre-filter already acted on.

    Stating them twice is what produced "Pour Joséphine : sans tomate" on nine
    dishes out of nine, several containing no tomato at all. The model was
    given a dislike and no way to honour it — every candidate had already been
    checked — so it did the only thing left and annotated. §6.2 is explicit
    that what SQL can decide never goes to the model; this is that rule applied
    to a case where the leak was cosmetic rather than unsafe, and still wrong.

    What was NOT enforced stays: an aversion the referential could not resolve,
    or one the pool could not afford, has the prompt as its only recourse.
    """
    if not enforced:
        return context

    lowered = {name.strip().lower() for name in enforced}
    return replace(
        context,
        members=tuple(
            replace(
                member,
                aversion_tags=tuple(
                    tag for tag in member.aversion_tags if tag.strip().lower() not in lowered
                ),
            )
            for member in context.members
        ),
    )


def _excluded_allergens(inputs: Sequence[MemberInput]) -> frozenset[str]:
    """Every allergen anyone at the table excludes, whatever the severity."""
    codes: set[str] = set()
    for entry in inputs:
        codes |= {str(code) for code in entry.severe_allergens | entry.intolerances}
    return frozenset(codes)


def _eater_safety(
    db: Session,
    catalogue: SqlCatalogue,
    inputs: Sequence[MemberInput],
    alias_to_member: dict[str, uuid.UUID],
) -> EaterSafety:
    """Assemble step 4's inputs, in ALIASES — no member entity crosses over (I5).

    Both severities are excluded per eater, not only intolerances. A severe
    allergen is already gone from the pool, so listing it here costs nothing
    and means the check does not depend on the pre-filter having done its job:
    two independent barriers rather than one, on the data where that matters.
    """
    by_member = {entry.member_id: entry for entry in inputs}
    excluded: dict[str, frozenset[str]] = {}
    stage_by_eater: dict[str, str] = {}
    for alias, member_id in alias_to_member.items():
        entry = by_member.get(member_id)
        if entry is None:
            continue
        excluded[alias] = frozenset(entry.severe_allergens | entry.intolerances)
        stage_by_eater[alias] = entry.life_stage.value

    handles = catalogue.candidate_handles()
    recipe_ids = [catalogue.resolve(handle) for handle in handles]
    known = [recipe_id for recipe_id in recipe_ids if recipe_id is not None]

    allergens: dict[uuid.UUID, set[str]] = {}
    stages: dict[uuid.UUID, set[str]] = {}
    if known:
        for recipe_id, code in db.execute(
            select(RecipeAllergen.recipe_id, RecipeAllergen.allergen_code).where(
                RecipeAllergen.recipe_id.in_(known)
            )
        ).all():
            allergens.setdefault(recipe_id, set()).add(code.value)
        for recipe_id, stage in db.execute(
            select(RecipeSuitableStage.recipe_id, RecipeSuitableStage.life_stage).where(
                RecipeSuitableStage.recipe_id.in_(known)
            )
        ).all():
            stages.setdefault(recipe_id, set()).add(stage.value)

    # What a serving variant is allowed to name. Resolved ingredients only:
    # a line the referential never recognised cannot be echoed back by the
    # model, and rejecting it is more honest than accepting a name nobody can
    # check. Folded the same way `_check_removals_are_real` folds — case and
    # surrounding space, nothing more.
    ingredients: dict[uuid.UUID, set[str]] = {}
    if known:
        for recipe_id, name in db.execute(
            select(RecipeIngredient.recipe_id, Ingredient.canonical_name)
            .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
            .where(
                RecipeIngredient.recipe_id.in_(known),
                RecipeIngredient.is_section.is_(False),
            )
        ).all():
            ingredients.setdefault(recipe_id, set()).add(name.strip().casefold())

    return EaterSafety(
        allergens_by_recipe={
            handle: frozenset(allergens.get(recipe_id, set()))
            for handle, recipe_id in zip(handles, recipe_ids, strict=True)
            if recipe_id is not None
        },
        excluded_by_eater=excluded,
        stages_by_recipe={
            handle: frozenset(stages.get(recipe_id, set()))
            for handle, recipe_id in zip(handles, recipe_ids, strict=True)
            if recipe_id is not None
        },
        stage_by_eater=stage_by_eater,
        ingredients_by_recipe={
            handle: frozenset(ingredients.get(recipe_id, set()))
            for handle, recipe_id in zip(handles, recipe_ids, strict=True)
            if recipe_id is not None
        },
    )


def _store_removals(
    db: Session, dish: PlannedDish, member_id: uuid.UUID, names: Sequence[str]
) -> None:
    """Turn the names the model echoed into ingredient rows.

    Resolved against THIS recipe's own ingredients, never against the whole
    referential. `validate_proposal` has already rejected a name the recipe
    does not contain, so anything unmatched here is a spelling the fold missed
    — dropped in silence rather than stored as a removal nobody can trace.

    Nothing is written for a free-text dish: with no `recipe_id` there is no
    ingredient list to point at, and a removal that references nothing is worse
    than none.
    """
    if not names or dish.recipe_id is None:
        return

    by_name = {
        name.strip().casefold(): ingredient_id
        for ingredient_id, name in db.execute(
            select(Ingredient.id, Ingredient.canonical_name)
            .join(RecipeIngredient, RecipeIngredient.ingredient_id == Ingredient.id)
            .where(
                RecipeIngredient.recipe_id == dish.recipe_id,
                RecipeIngredient.is_section.is_(False),
            )
        ).all()
    }

    for name in names:
        ingredient_id = by_name.get(name.strip().casefold())
        if ingredient_id is not None:
            db.add(
                PlannedDishMemberRemoval(
                    planned_dish_id=dish.id,
                    member_id=member_id,
                    ingredient_id=ingredient_id,
                )
            )


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
                # `variant_confirmed_at` is deliberately NOT set here. A
                # variant arrives unconfirmed and stays so until a parent says
                # otherwise — that is the whole point of the column, and
                # writing a timestamp at generation would make the system
                # confirm its own proposal (§4.9).
                _store_removals(db, dish, member_id, proposed.variant_removals.get(alias, ()))

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


def revalidate_plans(db: Session, household_id: uuid.UUID, *, from_week: date) -> int:
    """Re-check the plans already written against the constraints as they stand.

    This is the whole reason `UX-V0.md` §15's allergen banner could be removed
    rather than merely reworded. The dangerous case is concrete and singular:
    someone declares an allergy on Tuesday for a week composed on Monday, when
    nothing filtered it. A banner would ask them to re-read nine slots by hand;
    re-validation tells them exactly which ones.

    Deterministic and free — no model call, the same SQL the pre-filter uses.
    Past weeks are left alone: they were eaten, and rewriting history to say a
    meal was unsafe helps nobody.

    Returns the number of plans whose violations changed.
    """
    members = _members_of(db, household_id)
    if not members:
        return 0
    household = household_filter(db, household_id, members)

    plans = list(
        db.scalars(
            select(MealPlan).where(
                MealPlan.household_id == household_id, MealPlan.week_start >= from_week
            )
        )
    )
    changed = 0

    for plan in plans:
        dishes = list(
            db.scalars(select(PlannedDish).where(PlannedDish.meal_plan_id == plan.id))
        )
        recipe_ids = [dish.recipe_id for dish in dishes if dish.recipe_id]

        allergens: dict[uuid.UUID, set[str]] = {}
        verified: dict[uuid.UUID, bool] = {}
        if recipe_ids:
            for recipe_id, code in db.execute(
                select(RecipeAllergen.recipe_id, RecipeAllergen.allergen_code).where(
                    RecipeAllergen.recipe_id.in_(recipe_ids)
                )
            ).all():
                allergens.setdefault(recipe_id, set()).add(code.value)
            verified = dict(
                db.execute(
                    select(Recipe.id, Recipe.allergens_verified).where(Recipe.id.in_(recipe_ids))
                ).all()
            )

        found: list[Violation] = []
        for dish in dishes:
            if dish.recipe_id is None:
                continue
            carried = allergens.get(dish.recipe_id, set())
            clashing = sorted(carried & household.excluded_allergens)
            if clashing:
                found.append(
                    Violation(
                        ALLERGEN_ON_PLANNED_DISH,
                        f"this dish carries {', '.join(clashing)}",
                        dish.day_of_week,
                        dish.meal_type,
                    )
                )
            elif household.require_verified and not verified.get(dish.recipe_id, False):
                found.append(
                    Violation(
                        UNVERIFIED_ON_PLANNED_DISH,
                        "this dish's ingredients were not all recognised",
                        dish.day_of_week,
                        dish.meal_type,
                    )
                )

        # Only OUR codes are replaced. A `too_many_dishes` recorded at
        # generation still describes the plan, and dropping it here would make
        # adding an aversion quietly erase an unrelated warning.
        ours = {ALLERGEN_ON_PLANNED_DISH, UNVERIFIED_ON_PLANNED_DISH}
        kept = [entry for entry in (plan.violations or []) if entry.get("code") not in ours]
        rewritten = kept + [
            {
                "code": violation.code,
                "detail": violation.detail,
                "day_of_week": violation.day_of_week,
                "meal_type": violation.meal_type,
            }
            for violation in found
        ]
        if rewritten != (plan.violations or []):
            plan.violations = rewritten
            changed += 1

    db.commit()
    return changed
