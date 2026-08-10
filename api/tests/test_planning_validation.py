"""Re-validation of a proposed plan — the deterministic core.

Every check here runs in V0. Only the envelope check (`DISH_OUTSIDE_CANDIDATES`)
is dormant, because the pre-filter is stubbed and there is no candidate set to
enforce yet.
"""

from __future__ import annotations

import pytest

from app.domain.enums import MealType
from app.domain.planning import (
    DISH_OUTSIDE_CANDIDATES,
    DISH_WITHOUT_EATER,
    DISH_WITHOUT_IDENTITY,
    DUPLICATE_SLOT,
    EATER_NOT_SERVED,
    EATER_SERVED_TWICE,
    EMPTY_SLOT,
    MISSING_SLOT,
    TOO_MANY_DISHES,
    UNKNOWN_EATER,
    UNKNOWN_SLOT,
    VARIANT_FOR_NON_EATER,
    ProposedDish,
    ProposedSlot,
    SlotSpec,
    repair_hint,
    validate_proposal,
)

MONDAY_DINNER = SlotSpec(0, MealType.DINNER, ("m1", "m2", "m3"))
TUESDAY_DINNER = SlotSpec(1, MealType.DINNER, ("m1", "m2", "m3"))
SPEC = [MONDAY_DINNER, TUESDAY_DINNER]


def slot(day: int, *dishes: ProposedDish) -> ProposedSlot:
    return ProposedSlot(day_of_week=day, meal_type=MealType.DINNER, dishes=dishes)


def dish(*eaters: str, label: str = "Poulet aux olives", **kwargs: object) -> ProposedDish:
    return ProposedDish(eater_aliases=eaters, label=label, **kwargs)  # type: ignore[arg-type]


def codes(violations: list) -> set[str]:
    return {violation.code for violation in violations}


def test_everyone_eating_the_same_dish_is_valid() -> None:
    """The best outcome: one preparation for the whole household."""
    proposal = [
        slot(0, dish("m1", "m2", "m3")),
        slot(1, dish("m1", "m2", "m3", label="Gratin de courgettes")),
    ]
    assert validate_proposal(proposal, SPEC) == []


def test_two_dishes_with_a_split_household_is_valid() -> None:
    proposal = [
        slot(0, dish("m1", "m2"), dish("m3", label="Purée de carottes")),
        slot(1, dish("m1", "m2", "m3", label="Gratin")),
    ]
    assert validate_proposal(proposal, SPEC) == []


def test_serving_variant_is_valid_and_is_the_preferred_shape() -> None:
    """One preparation, different plates — the cheapest way to feed diverging needs."""
    proposal = [
        slot(0, dish("m1", "m2", "m3", serving_variants={"m3": "sans olives"})),
        slot(1, dish("m1", "m2", "m3", label="Gratin")),
    ]
    assert validate_proposal(proposal, SPEC) == []


def test_variant_targeting_someone_who_does_not_eat_the_dish() -> None:
    proposal = [
        slot(
            0,
            dish("m1", "m2", serving_variants={"m3": "sans olives"}),
            dish("m3", label="Purée"),
        ),
        slot(1, dish("m1", "m2", "m3", label="Gratin")),
    ]
    assert VARIANT_FOR_NON_EATER in codes(validate_proposal(proposal, SPEC))


# --- Slot coverage -----------------------------------------------------------


def test_missing_slot_is_reported() -> None:
    proposal = [slot(0, dish("m1", "m2", "m3"))]
    assert MISSING_SLOT in codes(validate_proposal(proposal, SPEC))


def test_invented_slot_is_reported() -> None:
    proposal = [
        slot(0, dish("m1", "m2", "m3")),
        slot(1, dish("m1", "m2", "m3")),
        slot(5, dish("m1", "m2", "m3")),  # never requested
    ]
    assert UNKNOWN_SLOT in codes(validate_proposal(proposal, SPEC))


def test_duplicated_slot_is_reported() -> None:
    proposal = [
        slot(0, dish("m1", "m2", "m3")),
        slot(0, dish("m1", "m2", "m3")),
        slot(1, dish("m1", "m2", "m3")),
    ]
    assert DUPLICATE_SLOT in codes(validate_proposal(proposal, SPEC))


def test_empty_slot_is_reported() -> None:
    proposal = [slot(0), slot(1, dish("m1", "m2", "m3"))]
    assert EMPTY_SLOT in codes(validate_proposal(proposal, SPEC))


# --- Assignment --------------------------------------------------------------


def test_eater_left_out_is_reported() -> None:
    proposal = [
        slot(0, dish("m1", "m2")),  # m3 eats nothing
        slot(1, dish("m1", "m2", "m3")),
    ]
    assert EATER_NOT_SERVED in codes(validate_proposal(proposal, SPEC))


def test_eater_served_twice_is_reported() -> None:
    proposal = [
        slot(0, dish("m1", "m2", "m3"), dish("m3", label="Purée")),
        slot(1, dish("m1", "m2", "m3")),
    ]
    assert EATER_SERVED_TWICE in codes(validate_proposal(proposal, SPEC))


def test_unknown_eater_is_reported() -> None:
    proposal = [
        slot(0, dish("m1", "m2", "m3", "m9")),
        slot(1, dish("m1", "m2", "m3")),
    ]
    assert UNKNOWN_EATER in codes(validate_proposal(proposal, SPEC))


def test_dish_feeding_nobody_is_reported() -> None:
    proposal = [
        slot(0, dish("m1", "m2", "m3"), dish(label="Purée orpheline")),
        slot(1, dish("m1", "m2", "m3")),
    ]
    assert DISH_WITHOUT_EATER in codes(validate_proposal(proposal, SPEC))


@pytest.mark.parametrize("label", ["", "   ", None])
def test_dish_without_identity_is_reported(label: str | None) -> None:
    proposal = [
        slot(0, ProposedDish(eater_aliases=("m1", "m2", "m3"), label=label)),
        slot(1, dish("m1", "m2", "m3")),
    ]
    assert DISH_WITHOUT_IDENTITY in codes(validate_proposal(proposal, SPEC))


# --- Dish count --------------------------------------------------------------


def test_three_dishes_for_three_eaters_is_allowed() -> None:
    """The soft limit is a scoring penalty, never a hard constraint.

    A household with a baby, a lactose-intolerant member and a teenager
    mechanically needs three dishes. Rejecting that would make a perfectly
    ordinary household infeasible.
    """
    proposal = [
        slot(0, dish("m1"), dish("m2", label="Gratin"), dish("m3", label="Purée")),
        slot(1, dish("m1", "m2", "m3")),
    ]
    assert validate_proposal(proposal, SPEC) == []


def test_more_dishes_than_eaters_is_reported() -> None:
    """The only hard bound: at worst one dish per eater."""
    spec = [SlotSpec(0, MealType.DINNER, ("m1", "m2"))]
    proposal = [
        slot(0, dish("m1"), dish("m2", label="Gratin"), dish(label="Purée en trop")),
    ]
    assert TOO_MANY_DISHES in codes(validate_proposal(proposal, spec))


# --- The envelope ------------------------------------------------------------


def test_envelope_is_inactive_when_unbounded() -> None:
    """V0: the pre-filter is stubbed, so any dish identity is acceptable."""
    proposal = [
        slot(0, ProposedDish(eater_aliases=("m1", "m2", "m3"), recipe_id="r_invented")),
        slot(1, dish("m1", "m2", "m3")),
    ]
    assert validate_proposal(proposal, SPEC, allowed_recipe_ids=None) == []


def test_dish_outside_the_candidate_set_is_rejected() -> None:
    """V1: THE envelope check. A model that steps outside is caught, always."""
    proposal = [
        slot(0, ProposedDish(eater_aliases=("m1", "m2", "m3"), recipe_id="r_invented")),
        slot(1, ProposedDish(eater_aliases=("m1", "m2", "m3"), recipe_id="r_012")),
    ]
    violations = validate_proposal(proposal, SPEC, allowed_recipe_ids=frozenset({"r_012", "r_037"}))
    assert DISH_OUTSIDE_CANDIDATES in codes(violations)
    assert len([v for v in violations if v.code == DISH_OUTSIDE_CANDIDATES]) == 1


# --- Reporting ---------------------------------------------------------------


def test_all_violations_are_returned_not_just_the_first() -> None:
    """One repair prompt should list everything, not discover it one retry at a time."""
    proposal = [slot(0, dish("m1", "m9"))]
    violations = validate_proposal(proposal, SPEC)

    assert {MISSING_SLOT, UNKNOWN_EATER, EATER_NOT_SERVED} <= codes(violations)


def test_repair_hint_mentions_every_violation() -> None:
    violations = validate_proposal([slot(0, dish("m1", "m2"))], SPEC)
    hint = repair_hint(violations)

    for violation in violations:
        assert violation.code in hint
