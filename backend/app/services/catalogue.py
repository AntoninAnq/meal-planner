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
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Ingredient,
    IngredientAlias,
    MealPlan,
    PlannedDish,
    Recipe,
    RecipeAllergen,
    RecipeIngredient,
    RecipeSuitableStage,
)
from app.domain.enums import DishType, LifeStage
from app.domain.ingredient_names import normalise, variants
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

#: What a complexity rating is called in the prompt. The model reads French
#: here for the same reason the dish titles are French: they are shown as-is.
COMPLEXITY_LABELS = {1: "simple", 2: "moyen", 3: "long"}

#: How many DISTINCTIVE ingredients two candidates must share before it is
#: worth telling the model.
OVERLAP_THRESHOLD = 3

#: An ingredient present in more than this share of the candidate set is not a
#: shared base, it is pantry. Measured on a real run: with a plain count, salt,
#: olive oil and garlic put twelve unrelated recipes in one "family" — a signal
#: that fires everywhere carries nothing, which is the trap this constant
#: exists to avoid.
UBIQUITOUS_SHARE = 0.25

#: …but never fewer than this many candidates. A pool smaller than the
#: 60-candidate floor happens when the household's constraints leave little,
#: and that is exactly when the signal must not eat itself.
UBIQUITOUS_FLOOR = 4

#: How many overlap groups reach the prompt. Enough to plan a week around,
#: short enough not to drown the candidate list it comments on.
OVERLAP_GROUPS_SHOWN = 8

#: How many ingredients a candidate line shows. Enough for the model to tell a
#: gratin from a curry, short enough that the line stays around 31 tokens.
INGREDIENTS_SHOWN = 5


def candidate_count(*, slots: int, dishes_per_slot: int) -> int:
    return max(CANDIDATE_FLOOR, min(CANDIDATE_CEILING, CANDIDATE_MARGIN * slots * dishes_per_slot))


def overlap_groups(by_handle: Mapping[str, frozenset[uuid.UUID]]) -> list[str]:
    """Which candidates share a base, so a week can be planned around one.

    This is the V1 promise of `UX-V0.md` §12 — "lundi et jeudi partagent une
    base" — and the only one of the four signals that differentiates the
    product. Computable today because 74.7 % of ingredient lines resolve.

    **Pantry ingredients are removed first, and that is the whole difficulty.**
    A plain shared-ingredient count put twelve unrelated recipes in one family
    on the first real run: salt, olive oil and garlic are in almost everything,
    so every pair cleared the threshold. An ingredient present in more than a
    quarter of the candidates is not a shared base, it is a cupboard.

    Grouped rather than listed pair by pair: `r_005 + r_018`, `r_005 + r_042`,
    `r_018 + r_042` is one fact written three times, and the model would have
    to rebuild the family from it.
    """
    handles = sorted(by_handle)
    counts: dict[uuid.UUID, int] = {}
    for ids in by_handle.values():
        for ingredient_id in ids:
            counts[ingredient_id] = counts.get(ingredient_id, 0) + 1

    # The floor keeps the rule sane on a small pool: at 8 candidates, a
    # quarter is two, and a base genuinely shared by three dishes would be
    # written off as pantry.
    ceiling = max(UBIQUITOUS_FLOOR, int(len(handles) * UBIQUITOUS_SHARE))
    common = {ingredient_id for ingredient_id, n in counts.items() if n > ceiling}
    distinctive = {handle: by_handle[handle] - common for handle in handles}

    groups: list[list[str]] = []
    placed: set[str] = set()
    for index, handle in enumerate(handles):
        if handle in placed or not distinctive[handle]:
            continue
        family = [handle]
        for other in handles[index + 1 :]:
            if other in placed or not distinctive[other]:
                continue
            if len(distinctive[handle] & distinctive[other]) >= OVERLAP_THRESHOLD:
                family.append(other)
                placed.add(other)
        if len(family) > 1:
            placed.add(handle)
            groups.append(family)

    groups.sort(key=len, reverse=True)
    return [", ".join(family) for family in groups[:OVERLAP_GROUPS_SHOWN]]


def rank(
    eligible: Sequence[uuid.UUID],
    *,
    last_planned: Mapping[uuid.UUID, date],
    seed: str,
    preferred: Collection[uuid.UUID] = (),
    wanted: Collection[uuid.UUID] = (),
    unwanted: Collection[uuid.UUID] = (),
) -> list[uuid.UUID]:
    """Safe for everyone first, then never served, then least recently served.

    `preferred` holds the recipes that carry no allergen anyone at the table
    excludes. They are ranked FIRST — not filtered, ranked. Nothing is
    forbidden: a recipe one member cannot eat stays in the pool and remains
    choosable as a second dish, which is the product's whole premise (§4.9).

    Why ordering is a real lever and not a decoration: the model was observed
    walking the candidate list in order, taking `r_008, r_007, r_005…` down the
    page. On the real catalogue the pool holds 390 recipes and only 60 reach
    the prompt, so putting the safe ones in front makes what the model sees
    mostly safe — and measured, it served an intolerant eater their allergen on
    9 assignments out of 45 when it was not.

    The deterministic check still runs afterwards (§6.2 step 4). This gives it
    less to do; it does not replace it.

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
    # Sorted before shuffling, and this is load-bearing rather than tidy. A
    # seeded shuffle is only reproducible if its INPUT order is: the first time
    # this ran twice on the same seed it returned different candidates, because
    # deriving `complexity` had rewritten the table and Postgres handed the
    # rows back in a new physical order. The whole "the reserve is recomputed,
    # never stored" design rests on this line.
    safe, asked, refused = set(preferred), set(wanted), set(unwanted)

    def tier(recipe_id: uuid.UUID) -> int:
        """Five bands, most wanted first. Ordering only — nothing is removed.

        `unwanted` lands last rather than being dropped: the household said
        "pas de poisson cette semaine", which is a preference, and a preference
        that silently deletes a third of the catalogue is a filter wearing a
        disguise.
        """
        if recipe_id in refused:
            return 4
        if recipe_id in asked:
            return 0 if recipe_id in safe else 1
        return 2 if recipe_id in safe else 3

    ordered: list[uuid.UUID] = []
    for band in range(5):
        group = [recipe_id for recipe_id in eligible if tier(recipe_id) == band]
        ordered += _by_staleness(group, last_planned, seed)
    return ordered


def _by_staleness(
    recipe_ids: Sequence[uuid.UUID], last_planned: Mapping[uuid.UUID, date], seed: str
) -> list[uuid.UUID]:
    fresh = sorted(
        (recipe_id for recipe_id in recipe_ids if recipe_id not in last_planned), key=str
    )
    served = sorted(
        (recipe_id for recipe_id in recipe_ids if recipe_id in last_planned),
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
    #: Declared prep + cooking. None on the 22 % of the catalogue that says
    #: nothing — and then the line says nothing either, rather than implying
    #: a recipe is quick because no number was found.
    minutes: int | None = None
    #: 1..3, computed by formula (`catalog/complexity.py`), never judged.
    complexity: int | None = None

    def line(self) -> str:
        parts = [f"{self.handle} — {self.title}"]

        effort = " ".join(
            piece
            for piece in (
                f"{self.minutes} min" if self.minutes else "",
                COMPLEXITY_LABELS.get(self.complexity or 0, ""),
            )
            if piece
        )
        if effort:
            parts.append(effort)
        if self.ingredients:
            parts.append(", ".join(self.ingredients[:INGREDIENTS_SHOWN]))
        return " — ".join(parts)


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
        exclude: frozenset[uuid.UUID] = frozenset(),
        prefer_free_of: frozenset[str] = frozenset(),
        wanted_ingredients: frozenset[str] = frozenset(),
        unwanted_ingredients: frozenset[str] = frozenset(),
    ) -> None:
        self._db = db
        self._household = household
        self._limit = limit
        #: Recipes the household has just refused. Excluded from the pool
        #: entirely rather than merely ranked last: a directed repair that
        #: proposes the dish someone just said no to is the one answer that
        #: makes the feature useless.
        self._exclude = exclude
        #: Allergen codes someone at the table excludes. Recipes carrying none
        #: of them are ranked first — see `rank`. NOT a filter: the others stay
        #: in the pool for a second dish.
        self._prefer_free_of = prefer_free_of
        #: Ingredient names the household named this week — `leftover: jambon`
        #: ranks its recipes first, `avoid: poisson` ranks them last. Normalised
        #: names, resolved through the referential like any other line.
        self._wanted_ingredients = wanted_ingredients
        self._unwanted_ingredients = unwanted_ingredients
        self._ranked = self._rank(household_id, week_start)
        self._chosen = self._decorate(self._ranked[:limit])
        self._by_handle = {candidate.handle: candidate for candidate in self._chosen}
        self._ingredient_ids = self._resolved_ingredients(
            [candidate.recipe_id for candidate in self._chosen]
        )

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

    def signals(self, recipe_ids: frozenset[str]) -> list[str]:
        """Soft signals about the candidate set. They inform, never filter.

        Only overlap for now. Rotation by `food_category` is deliberately
        absent: the referential knows 16 protein ingredients, so 47 % of the
        eligible pool shows no identified protein and the signal would call a
        chicken tajine vegetarian. A signal that is confidently wrong is worse
        than an absent one — the model reads it as context and has no way to
        contradict it. It comes back when the referential recognises a protein
        in more than half the pool.
        """
        return self._overlap(recipe_ids)

    def _overlap(self, recipe_ids: frozenset[str]) -> list[str]:
        handles = [handle for handle in sorted(recipe_ids) if handle in self._by_handle]
        return overlap_groups(
            {
                handle: self._ingredient_ids.get(self._by_handle[handle].recipe_id, frozenset())
                for handle in handles
            }
        )

    # -- Beyond the port --------------------------------------------------

    def candidate_handles(self) -> list[str]:
        """The handles shown to the model, in the order they were shown."""
        return [candidate.handle for candidate in self._chosen]

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

    def alternatives(self, *, exclude: set[uuid.UUID], limit: int) -> list[Candidate]:
        """What to offer someone who says "not that one".

        Taken from the ranking in order, so the first alternatives are the ones
        the model itself was shown and passed over — `UX-V0.md` §6 calls them
        *les candidats écartés*, and they are the cheapest possible answer: no
        model call, a few tens of milliseconds.

        Nothing was stored to make this work. The ranking is seeded on
        `household_id` and `week_start`, so rebuilding it here reproduces
        exactly the list that was used to generate the plan.
        """
        offered = [recipe_id for recipe_id in self._ranked if recipe_id not in exclude]
        return self._decorate(offered[:limit])

    def detail(self, recipe_ids: list[uuid.UUID]) -> list[Candidate]:
        """Titles, effort and ingredients for an arbitrary set."""
        return self._decorate(recipe_ids)

    def _resolved_ingredients(
        self, recipe_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
        """Only the candidates shown: overlap is a comment on the prompt."""
        if not recipe_ids:
            return {}
        rows = self._db.execute(
            select(RecipeIngredient.recipe_id, RecipeIngredient.ingredient_id).where(
                RecipeIngredient.recipe_id.in_(recipe_ids),
                RecipeIngredient.ingredient_id.is_not(None),
                RecipeIngredient.is_section.is_(False),
            )
        ).all()
        grouped: dict[uuid.UUID, set[uuid.UUID]] = {}
        for recipe_id, ingredient_id in rows:
            grouped.setdefault(recipe_id, set()).add(ingredient_id)
        return {recipe_id: frozenset(ids) for recipe_id, ids in grouped.items()}

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

        if self._exclude:
            statement = statement.where(Recipe.id.not_in(sorted(self._exclude)))

        # Explicit order for the same reason `rank` sorts: an unordered
        # SELECT is free to change its mind after any table rewrite.
        return list(self._db.scalars(statement.order_by(Recipe.id)))

    def _last_planned(self, household_id: uuid.UUID) -> dict[uuid.UUID, date]:
        rows = self._db.execute(
            select(PlannedDish.recipe_id, func.max(MealPlan.week_start))
            .join(MealPlan, MealPlan.id == PlannedDish.meal_plan_id)
            .where(MealPlan.household_id == household_id, PlannedDish.recipe_id.is_not(None))
            .group_by(PlannedDish.recipe_id)
        ).all()
        return {recipe_id: last for recipe_id, last in rows}

    def _rank(self, household_id: uuid.UUID, week_start: date) -> list[uuid.UUID]:
        eligible = self._eligible()
        return rank(
            eligible,
            last_planned=self._last_planned(household_id),
            seed=f"{household_id}:{week_start.isoformat()}",
            preferred=self._free_of(eligible, self._prefer_free_of),
            wanted=self._containing(eligible, self._wanted_ingredients),
            unwanted=self._containing(eligible, self._unwanted_ingredients),
        )

    def _containing(self, recipe_ids: list[uuid.UUID], names: frozenset[str]) -> set[uuid.UUID]:
        """Recipes holding any of these ingredients, resolved through the referential.

        The household writes `jambon`; the catalogue holds an ingredient id.
        The same normalisation the resolution pass uses does the mapping, so a
        request lands on exactly the recipes a human would say contain it — and
        a word the referential does not know matches nothing, silently and
        correctly.
        """
        if not names or not recipe_ids:
            return set()

        # A local index rather than the pipeline's: `app.catalog` is off limits
        # to anything served over HTTP (`tests/test_catalog_boundaries.py`), and
        # this is three lines of the same two tables.
        index: dict[str, uuid.UUID] = {}
        for ingredient in self._db.scalars(select(Ingredient)):
            index[ingredient.normalized_name] = ingredient.id
        for alias in self._db.scalars(select(IngredientAlias)):
            index.setdefault(alias.normalized_name, alias.ingredient_id)

        ingredient_ids: set[uuid.UUID] = set()
        for name in names:
            spelling = normalise(name)
            # Exact first, then the same relaxation resolution uses — someone
            # typing `courgettes` must land on `courgette`.
            found = index.get(spelling) or next(
                (index[candidate] for candidate in variants(spelling) if candidate in index),
                None,
            )
            if found is not None:
                ingredient_ids.add(found)
        if not ingredient_ids:
            return set()

        return {
            recipe_id
            for (recipe_id,) in self._db.execute(
                select(RecipeIngredient.recipe_id).where(
                    RecipeIngredient.recipe_id.in_(recipe_ids),
                    RecipeIngredient.ingredient_id.in_(sorted(ingredient_ids)),
                )
            ).all()
        }

    def _free_of(
        self, recipe_ids: list[uuid.UUID], codes: frozenset[str]
    ) -> set[uuid.UUID]:
        """Recipes carrying none of the allergens anyone at the table excludes."""
        if not codes or not recipe_ids:
            return set()
        carriers = {
            recipe_id
            for (recipe_id,) in self._db.execute(
                select(RecipeAllergen.recipe_id).where(
                    RecipeAllergen.recipe_id.in_(recipe_ids),
                    RecipeAllergen.allergen_code.in_(sorted(codes)),
                )
            ).all()
        }
        return {recipe_id for recipe_id in recipe_ids if recipe_id not in carriers}

    def _decorate(self, shown: list[uuid.UUID]) -> list[Candidate]:
        """Titles and ingredients for the candidates that reach the prompt.

        Handles are assigned here, so they number the SHOWN set — `r_000` is
        the first candidate the model sees, and the reserve has none until it
        is decorated in its turn.
        """
        rows = self._db.execute(
            select(Recipe.id, Recipe.title, Recipe.prep_minutes, Recipe.cook_minutes,
                   Recipe.complexity).where(Recipe.id.in_(shown))
        ).all()
        meta = {
            recipe_id: (
                title,
                (prep or 0) + (cook or 0) if (prep is not None or cook is not None) else None,
                complexity,
            )
            for recipe_id, title, prep, cook, complexity in rows
        }

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
            title, minutes, complexity = meta.get(recipe_id, ("", None, None))
            candidates.append(
                Candidate(
                    handle=f"r_{index:03d}",
                    recipe_id=recipe_id,
                    title=title,
                    ingredients=ingredients.get(recipe_id, []),
                    minutes=minutes,
                    complexity=complexity,
                )
            )
        return candidates
