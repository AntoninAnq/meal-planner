"""The `baby` exception of §4.9 — the only place `STAGE_FOR_EATER` bends.

Zero of the 3 439 catalogue recipes carries `baby` in `suitable_stages`, so
§4.3 read literally means a household with a child under 18 months is never
served: that is exactly what V1 did, by dropping the stage out of the grid.

A serving variant now opens the assignment. I1 holds because what makes it
legitimate is the PARENT confirming the variant, not the model writing one —
and re-validation runs long before any parent has seen anything, so all it can
demand is that a variant was proposed at all.

What must NOT bend is checked here too, because an exception that quietly
widens is worse than no exception.
"""

from __future__ import annotations

from app.domain.enums import MealType
from app.domain.planning import (
    ALLERGEN_FOR_EATER,
    STAGE_FOR_EATER,
    EaterSafety,
    ProposedDish,
    ProposedSlot,
    SlotSpec,
    validate_proposal,
)

ADULT_ONLY = frozenset({"teen_adult", "young_child"})

SPEC = [SlotSpec(0, MealType.DINNER, ("m1", "m2"))]


def _safety(**overrides: object) -> EaterSafety:
    base: dict[str, object] = {
        "stages_by_recipe": {"r_001": ADULT_ONLY},
        "stage_by_eater": {"m1": "teen_adult", "m2": "baby"},
        "allergens_by_recipe": {"r_001": frozenset()},
        "excluded_by_eater": {},
    }
    base.update(overrides)
    return EaterSafety(**base)  # type: ignore[arg-type]


def _plan(**dish_kwargs: object) -> list[ProposedSlot]:
    return [
        ProposedSlot(
            0,
            MealType.DINNER,
            (ProposedDish(eater_aliases=("m1", "m2"), recipe_id="r_001", **dish_kwargs),),  # type: ignore[arg-type]
        )
    ]


def _codes(violations: list) -> list[str]:  # type: ignore[type-arg]
    return [violation.code for violation in violations]


def test_a_baby_on_an_adult_dish_with_no_variant_is_still_refused() -> None:
    """The mistake the prompt calls "always wrong", and it stays wrong.

    Without this, the exception would not be an exception — it would be the
    removal of the rule.
    """
    violations = validate_proposal(_plan(), SPEC, safety=_safety())

    assert STAGE_FOR_EATER in _codes(violations)


def test_a_variant_opens_the_assignment_for_a_baby() -> None:
    violations = validate_proposal(
        _plan(serving_variants={"m2": "part prélevée avant salage, écrasée"}),
        SPEC,
        safety=_safety(),
    )

    assert STAGE_FOR_EATER not in _codes(violations)


def test_an_empty_variant_is_not_a_variant() -> None:
    """A blank string is what a model returns when it has nothing to say.

    Treating it as consent would make the exception fire on exactly the dishes
    the model could not adapt.
    """
    violations = validate_proposal(
        _plan(serving_variants={"m2": ""}), SPEC, safety=_safety()
    )

    assert STAGE_FOR_EATER in _codes(violations)


def test_the_exception_does_not_extend_to_other_stages() -> None:
    """A variant never opens an assignment for a child or an adult.

    `young_child` has hundreds of catalogue recipes; it has no need of this,
    and letting it through would hand the model back the stage decision that
    §4.3 keeps in SQL.
    """
    violations = validate_proposal(
        _plan(serving_variants={"m2": "sans épices"}),
        SPEC,
        safety=_safety(
            stages_by_recipe={"r_001": frozenset({"teen_adult"})},
            stage_by_eater={"m1": "teen_adult", "m2": "young_child"},
        ),
    )

    assert STAGE_FOR_EATER in _codes(violations)


def test_a_variant_never_opens_an_allergen() -> None:
    """THE line that does not move.

    A variant describes how to serve. It cannot make a dish free of what it
    contains, and a model that writes "sans lait" on a gratin has described a
    different dish, not a way of serving this one.
    """
    violations = validate_proposal(
        _plan(serving_variants={"m2": "part prélevée, sans le lait"}),
        SPEC,
        safety=_safety(
            allergens_by_recipe={"r_001": frozenset({"milk"})},
            excluded_by_eater={"m2": frozenset({"milk"})},
        ),
    )

    assert ALLERGEN_FOR_EATER in _codes(violations)


def test_a_baby_on_a_dish_that_genuinely_suits_them_needs_no_variant() -> None:
    """The day the catalogue holds real baby recipes, nothing here applies."""
    violations = validate_proposal(
        _plan(),
        SPEC,
        safety=_safety(stages_by_recipe={"r_001": frozenset({"teen_adult", "baby"})}),
    )

    assert STAGE_FOR_EATER not in _codes(violations)
