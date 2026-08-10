"""The planning pipeline's deterministic core.

Pure functions: no database, no HTTP, no LLM. This is where the safety
guarantees live, so this is where the test coverage has to be serious.

The pipeline is always the same four steps:

    pre-filter (SQL, hard)  ->  soft signals (SQL)  ->  arbitration (LLM)
                                                     ->  re-validation (here)

In V0 the pre-filter is STUBBED — there is no catalogue, so it returns an
unbounded candidate set and the envelope check below has nothing to enforce. The
seam exists and is exercised; only its data is missing. That is deliberate: the
V0 must keep the final shape so that reaching V1 replaces two implementations
behind interfaces already in place, rather than rewriting the graph.

Everything here speaks in per-request ALIASES (`m1`, `m2`), never member ids —
see `prompt_context` and invariant I5.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.domain.enums import MealType


@dataclass(frozen=True)
class SlotSpec:
    """A slot the planner must fill, and who eats at it."""

    day_of_week: int
    meal_type: MealType
    eater_aliases: tuple[str, ...]

    @property
    def key(self) -> tuple[int, MealType]:
        return (self.day_of_week, self.meal_type)


@dataclass(frozen=True)
class ProposedDish:
    """One dish the model proposes, and who it assigns to it."""

    eater_aliases: tuple[str, ...]
    #: V0 works without a catalogue: the model proposes titles.
    label: str | None = None
    #: V1: an identifier drawn from the candidate set.
    recipe_id: str | None = None
    #: alias -> "sans olives". How to serve, never whether the
    #: assignment is allowed.
    serving_variants: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProposedSlot:
    day_of_week: int
    meal_type: MealType
    dishes: tuple[ProposedDish, ...]

    @property
    def key(self) -> tuple[int, MealType]:
        return (self.day_of_week, self.meal_type)


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - debugging convenience
        return f"{self.code}: {self.detail}"


# --- Violation codes ---------------------------------------------------------

MISSING_SLOT = "missing_slot"
UNKNOWN_SLOT = "unknown_slot"
DUPLICATE_SLOT = "duplicate_slot"
EMPTY_SLOT = "empty_slot"
DISH_WITHOUT_EATER = "dish_without_eater"
DISH_WITHOUT_IDENTITY = "dish_without_identity"
UNKNOWN_EATER = "unknown_eater"
EATER_NOT_SERVED = "eater_not_served"
EATER_SERVED_TWICE = "eater_served_twice"
TOO_MANY_DISHES = "too_many_dishes"
DISH_OUTSIDE_CANDIDATES = "dish_outside_candidates"
VARIANT_FOR_NON_EATER = "variant_for_non_eater"


def validate_proposal(
    proposal: Sequence[ProposedSlot],
    spec: Sequence[SlotSpec],
    allowed_recipe_ids: frozenset[str] | None = None,
) -> list[Violation]:
    """Re-validation step. Returns every violation found, never raises.

    `allowed_recipe_ids` is the envelope: the candidate set the pre-filter
    produced. `None` means "unbounded" — the V0 stub — and disables that single
    check while every structural one still applies.

    Returning ALL violations rather than the first is what lets the repair
    prompt tell the model everything it got wrong in one go, instead of
    discovering them one retry at a time.
    """
    violations: list[Violation] = []
    by_key = {slot.key: slot for slot in spec}

    _check_slot_coverage(proposal, by_key, violations)

    for slot in proposal:
        expected = by_key.get(slot.key)
        if expected is None:
            continue  # already reported as UNKNOWN_SLOT
        _check_slot(slot, expected, allowed_recipe_ids, violations)

    return violations


def _check_slot_coverage(
    proposal: Sequence[ProposedSlot],
    by_key: Mapping[tuple[int, MealType], SlotSpec],
    violations: list[Violation],
) -> None:
    seen = Counter(slot.key for slot in proposal)

    for key, count in seen.items():
        if key not in by_key:
            violations.append(Violation(UNKNOWN_SLOT, f"day {key[0]} {key[1]} was not requested"))
        elif count > 1:
            violations.append(
                Violation(DUPLICATE_SLOT, f"day {key[0]} {key[1]} appears {count} times")
            )

    for key in by_key:
        if key not in seen:
            violations.append(Violation(MISSING_SLOT, f"day {key[0]} {key[1]} is missing"))


def _check_slot(
    slot: ProposedSlot,
    expected: SlotSpec,
    allowed_recipe_ids: frozenset[str] | None,
    violations: list[Violation],
) -> None:
    where = f"day {slot.day_of_week} {slot.meal_type}"

    if not slot.dishes:
        violations.append(Violation(EMPTY_SLOT, f"{where} has no dish"))
        return

    # The soft limit on dish count is a scoring penalty, never a hard
    # constraint — a household with a baby, a lactose-intolerant member and a
    # teenager mechanically needs three dishes. The only hard bound is "at worst
    # one dish per eater", which is trivially satisfiable.
    if len(slot.dishes) > len(expected.eater_aliases):
        violations.append(
            Violation(
                TOO_MANY_DISHES,
                f"{where} has {len(slot.dishes)} dishes for {len(expected.eater_aliases)} eater(s)",
            )
        )

    allowed_eaters = set(expected.eater_aliases)
    served: Counter[str] = Counter()

    for dish in slot.dishes:
        _check_dish(dish, where, allowed_eaters, allowed_recipe_ids, violations)
        served.update(dish.eater_aliases)

    for alias in expected.eater_aliases:
        if served[alias] == 0:
            violations.append(Violation(EATER_NOT_SERVED, f"{where}: {alias} eats nothing"))
        elif served[alias] > 1:
            violations.append(
                Violation(
                    EATER_SERVED_TWICE,
                    f"{where}: {alias} is assigned to {served[alias]} dishes",
                )
            )


def _check_dish(
    dish: ProposedDish,
    where: str,
    allowed_eaters: set[str],
    allowed_recipe_ids: frozenset[str] | None,
    violations: list[Violation],
) -> None:
    if dish.recipe_id is None and not (dish.label or "").strip():
        violations.append(
            Violation(DISH_WITHOUT_IDENTITY, f"{where}: a dish has neither recipe nor label")
        )

    if not dish.eater_aliases:
        name = dish.recipe_id or dish.label or "?"
        violations.append(Violation(DISH_WITHOUT_EATER, f"{where}: '{name}' feeds nobody"))

    for alias in dish.eater_aliases:
        if alias not in allowed_eaters:
            violations.append(
                Violation(UNKNOWN_EATER, f"{where}: '{alias}' does not eat at this slot")
            )

    # THE envelope check. Inactive in V0 (allowed_recipe_ids is None) because the
    # pre-filter is stubbed, active and load-bearing from V1 on.
    outside_envelope = (
        allowed_recipe_ids is not None
        and dish.recipe_id is not None
        and dish.recipe_id not in allowed_recipe_ids
    )
    if outside_envelope:
        violations.append(
            Violation(
                DISH_OUTSIDE_CANDIDATES,
                f"{where}: '{dish.recipe_id}' is not among the pre-filtered candidates",
            )
        )

    for alias in dish.serving_variants:
        if alias not in dish.eater_aliases:
            violations.append(
                Violation(
                    VARIANT_FOR_NON_EATER,
                    f"{where}: a serving variant targets '{alias}', who does not eat this dish",
                )
            )


def repair_hint(violations: Sequence[Violation]) -> str:
    """Turn violations into something a model can act on."""
    lines = "\n".join(f"- {violation}" for violation in violations)
    return "Your previous plan was rejected for the following reasons. Fix all of them:\n" + lines
