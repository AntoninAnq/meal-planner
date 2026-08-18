"""The pre-filter: the catalogue, seen through one household's constraints.

Step 1 of the §6.2 pipeline, and the implementation of `CataloguePort` that
replaces the V0 stub. Deterministic, SQL only, no model call — a candidate that
reaches the arbitration has already been cleared, so nothing the model does can
put an excluded allergen on a plate (I1).

**Handles, not UUIDs.** The model is shown `r_012`, never
`4f3c…-…-…`. A UUID costs ~15 tokens against 4 for a handle, which over 120
candidates is 1 300 tokens of context spent on identifiers. The mapping back is
held for the request; `eval/README.md` already writes its goldens this way.

**Three filters, and only the first two are about safety.**

* Household-wide severe allergens exclude a recipe outright — nobody at the
  table can be served it, so it has no business in the envelope.
* `allergens_verified` becomes mandatory as soon as the household declares ANY
  allergen constraint, severe or intolerance (§6.2). On an unverified recipe
  `recipe_allergen` is derived from the ingredients that resolved, so the
  absence of a tag means "we could not read", not "no allergen".
* `dish_type` keeps desserts, snacks, drinks, sides and components out of a
  meal slot. That one is quality, not safety, and NULL passes.

A per-member intolerance is deliberately NOT a filter here: the whole product
is that different people eat different things, so a recipe one member cannot
have is still a candidate for the others. That check belongs to re-validation,
where it applies per assignment.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Ingredient,
    MealPlan,
    PlannedDish,
    Recipe,
    RecipeAllergen,
    RecipeIngredient,
    RecipeSuitableStage,
)
from app.domain.enums import DishType, LifeStage
from app.domain.planning import SlotSpec

#: Dish types a meal slot never accepts. `main` and `starter` pass, and so does
#: NULL — 961 catalogue recipes carry no rubric anyone mapped, and excluding
#: them would spend a fifth of the catalogue on a comfort guarantee.
NOT_A_MEAL = (
    DishType.DESSERT,
    DishType.SNACK,
    DishType.BREAKFAST,
    DishType.DRINK,
    DishType.SIDE,
    DishType.COMPONENT,
)

#: How many candidates reach the prompt. Sized on the grid rather than guessed:
#: the default week is 9 slots and `max_dishes_soft_limit` is 2, so 18 dishes
#: are drawn; a candidate set must be several times that or the arbitration has
#: nothing to arbitrate (§6.1). Measured cost: 31 tokens a line, so 120 lines
#: are ~3 700 tokens — comfortable inside the 8 192-token window.
CANDIDATE_FLOOR = 60
CANDIDATE_CEILING = 120
CANDIDATE_MARGIN = 3

#: How many ingredients a candidate line shows. Enough for the model to tell a
#: gratin from a curry, short enough that the line stays around 31 tokens.
INGREDIENTS_SHOWN = 5


def candidate_count(*, slots: int, dishes_per_slot: int) -> int:
    return max(CANDIDATE_FLOOR, min(CANDIDATE_CEILING, CANDIDATE_MARGIN * slots * dishes_per_slot))


def rank(
    eligible: Sequence[uuid.UUID],
    *,
    last_planned: Mapping[uuid.UUID, date],
    seed: str,
) -> list[uuid.UUID]:
    """Never served first, then least recently served. Pure, so it is testable.

    The seed is `household_id` + `week_start`, and it buys two properties that
    pull in opposite directions. Replaying the same week yields the same
    candidates, so a regeneration is comparable, `GET …/alternatives` can serve
    the reserve without storing it, and the eval harness stays deterministic.
    But the NEXT week draws differently, so the catalogue turns — a purely
    deterministic ranking would show the same 60 recipes forever and the other
    two hundred would never exist.

    Freshness comes before staleness rather than being folded into one score:
    on a catalogue nobody has eaten from, every recipe is equally stale, and a
    single ordering would collapse to whatever the database returned first.
    """
    fresh = [recipe_id for recipe_id in eligible if recipe_id not in last_planned]
    served = sorted(
        (recipe_id for recipe_id in eligible if recipe_id in last_planned),
        key=lambda recipe_id: (last_planned[recipe_id], str(recipe_id)),
    )

    random.Random(seed).shuffle(fresh)
    return fresh + served


@dataclass(frozen=True)
class HouseholdFilter:
    """What the household's constraints mean for the catalogue.

    Deliberately carries no member entity and no member id — the pre-filter
    runs on the same side of the fence as the prompt builder (I5), and
    everything it needs is an aggregate.
    """

    #: Severe allergies, household scope. A recipe carrying one of these is out.
    excluded_allergens: frozenset[str] = frozenset()
    #: True as soon as ANY allergen constraint exists, severe or intolerance.
    require_verified: bool = False
    #: The stages present at the table. A recipe suiting none of them is out.
    life_stages: frozenset[LifeStage] = frozenset()


@dataclass
class Candidate:
    handle: str
    recipe_id: uuid.UUID
    title: str
    ingredients: list[str] = field(default_factory=list)

    def line(self) -> str:
        shown = ", ".join(self.ingredients[:INGREDIENTS_SHOWN])
        return f"{self.handle} — {self.title}" + (f" — {shown}" if shown else "")


class SqlCatalogue:
    """`CataloguePort` over the real catalogue.

    Built once per generation. The ranking is computed eagerly because the
    graph asks for candidates slot by slot and every slot shares the same pool:
    querying per slot would run the same statement nine times.
    """

    def __init__(
        self,
        db: Session,
        *,
        household_id: uuid.UUID,
        week_start: date,
        household: HouseholdFilter,
        limit: int,
    ) -> None:
        self._db = db
        self._household = household
        self._limit = limit
        self._ranked = self._rank(household_id, week_start)
        self._chosen = self._decorate(self._ranked[:limit])
        self._by_handle = {candidate.handle: candidate for candidate in self._chosen}

    # -- CataloguePort ----------------------------------------------------

    def candidates_for(self, slot: SlotSpec) -> frozenset[str] | None:
        """The envelope for this slot.

        The same set for every slot of a week: the hard constraints are
        household-level, and what varies between a Tuesday and a Saturday is a
        soft signal, not a filter. Returns an EMPTY set rather than None when
        the catalogue has nothing — `None` means unbounded, and answering it
        here would let the model invent dishes with no envelope at all.
        """
        return frozenset(self._by_handle)

    def describe(self, recipe_ids: frozenset[str]) -> list[str]:
        return [self._by_handle[handle].line() for handle in sorted(recipe_ids)
                if handle in self._by_handle]

    # -- Beyond the port --------------------------------------------------

    def resolve(self, handle: str) -> uuid.UUID | None:
        """Handle -> the real recipe. What `_persist` writes."""
        candidate = self._by_handle.get(handle)
        return candidate.recipe_id if candidate else None

    def title_of(self, handle: str) -> str | None:
        candidate = self._by_handle.get(handle)
        return candidate.title if candidate else None

    @property
    def reserve(self) -> list[uuid.UUID]:
        """Ranked recipes that did NOT reach the prompt, still in rank order.

        They cost nothing — no tokens, no storage — and they are what
        `GET …/alternatives` serves without an LLM call. Returned as bare ids
        rather than decorated candidates: rendering a line for two thousand
        recipes nobody will read is exactly the query that makes a synchronous
        endpoint slow for no reason. The caller decorates the handful it shows.

        Recomputable rather than stored: the ranking is seeded on
        `household_id` and `week_start`, so the same week always yields the
        same order.
        """
        return self._ranked[self._limit :]

    @property
    def pool_size(self) -> int:
        return len(self._ranked)

    # -- Ranking ----------------------------------------------------------

    def _eligible(self) -> list[uuid.UUID]:
        statement = select(Recipe.id).where(
            Recipe.dish_type.is_(None) | Recipe.dish_type.not_in(NOT_A_MEAL)
        )

        if self._household.require_verified:
            statement = statement.where(Recipe.allergens_verified.is_(True))

        if self._household.excluded_allergens:
            excluded = select(RecipeAllergen.recipe_id).where(
                RecipeAllergen.allergen_code.in_(sorted(self._household.excluded_allergens))
            )
            statement = statement.where(Recipe.id.not_in(excluded))

        if self._household.life_stages:
            suitable = select(RecipeSuitableStage.recipe_id).where(
                RecipeSuitableStage.life_stage.in_(sorted(self._household.life_stages))
            )
            statement = statement.where(Recipe.id.in_(suitable))

        return list(self._db.scalars(statement))

    def _last_planned(self, household_id: uuid.UUID) -> dict[uuid.UUID, date]:
        rows = self._db.execute(
            select(PlannedDish.recipe_id, func.max(MealPlan.week_start))
            .join(MealPlan, MealPlan.id == PlannedDish.meal_plan_id)
            .where(MealPlan.household_id == household_id, PlannedDish.recipe_id.is_not(None))
            .group_by(PlannedDish.recipe_id)
        ).all()
        return {recipe_id: last for recipe_id, last in rows}

    def _rank(self, household_id: uuid.UUID, week_start: date) -> list[uuid.UUID]:
        return rank(
            self._eligible(),
            last_planned=self._last_planned(household_id),
            seed=f"{household_id}:{week_start.isoformat()}",
        )

    def _decorate(self, shown: list[uuid.UUID]) -> list[Candidate]:
        """Titles and ingredients for the candidates that reach the prompt.

        Handles are assigned here, so they number the SHOWN set — `r_000` is
        the first candidate the model sees, and the reserve has none until it
        is decorated in its turn.
        """
        titles = dict(
            self._db.execute(select(Recipe.id, Recipe.title).where(Recipe.id.in_(shown))).all()
        )

        ingredients: dict[uuid.UUID, list[str]] = {}
        if shown:
            rows = self._db.execute(
                select(RecipeIngredient.recipe_id, Ingredient.canonical_name)
                .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
                .where(
                    RecipeIngredient.recipe_id.in_(shown),
                    RecipeIngredient.is_section.is_(False),
                )
                .order_by(RecipeIngredient.position)
            ).all()
            for recipe_id, name in rows:
                names = ingredients.setdefault(recipe_id, [])
                if name not in names:
                    names.append(name)

        candidates: list[Candidate] = []
        for index, recipe_id in enumerate(shown):
            candidates.append(
                Candidate(
                    handle=f"r_{index:03d}",
                    recipe_id=recipe_id,
                    title=titles.get(recipe_id, ""),
                    ingredients=ingredients.get(recipe_id, []),
                )
            )
        return candidates
