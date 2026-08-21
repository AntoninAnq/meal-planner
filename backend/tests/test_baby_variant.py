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
    UNKNOWN_REMOVAL,
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


# ---------------------------------------------------------------------------
# What a variant may say to remove
# ---------------------------------------------------------------------------

WITH_INGREDIENTS = {"ingredients_by_recipe": {"r_001": frozenset({"tomate", "courgette"})}}


def test_removing_something_the_recipe_does_not_contain_is_refused() -> None:
    """The measured failure, transposed to the plate that matters.

    On an aversion, this model wrote "sans tomate" beside an eater on nine
    dishes, several of which held no tomato — free text, nothing could catch
    it. Here the same sentence would be a safety instruction for a
    16-month-old, which a parent has every reason to believe.
    """
    violations = validate_proposal(
        _plan(
            serving_variants={"m2": "part prélevée, sans les noix"},
            variant_removals={"m2": ("Noix",)},
        ),
        SPEC,
        safety=_safety(**WITH_INGREDIENTS),
    )

    assert UNKNOWN_REMOVAL in _codes(violations)


def test_removing_an_ingredient_the_recipe_really_has_is_accepted() -> None:
    violations = validate_proposal(
        _plan(
            serving_variants={"m2": "part prélevée avant salage, écrasée"},
            variant_removals={"m2": ("Tomate",)},
        ),
        SPEC,
        safety=_safety(**WITH_INGREDIENTS),
    )

    assert UNKNOWN_REMOVAL not in _codes(violations)


def test_the_name_is_matched_on_case_and_spacing_only() -> None:
    """The model echoes a name it was shown, it does not paraphrase.

    Folding case and space absorbs the copy; anything looser would start
    guessing what it meant, which is how a wrong removal gets accepted.
    """
    violations = validate_proposal(
        _plan(serving_variants={"m2": "x"}, variant_removals={"m2": ("  TOMATE ",)}),
        SPEC,
        safety=_safety(**WITH_INGREDIENTS),
    )

    assert UNKNOWN_REMOVAL not in _codes(violations)


def test_nothing_is_checked_when_the_ingredients_are_unknown() -> None:
    """V0 and the slot-scoped repair pass no ingredients.

    Rejecting there would fail plans for lacking data the caller never
    supplied — a check that fires on absence is a check that fires everywhere.
    """
    violations = validate_proposal(
        _plan(serving_variants={"m2": "x"}, variant_removals={"m2": ("Chose",)}),
        SPEC,
        safety=_safety(),
    )

    assert UNKNOWN_REMOVAL not in _codes(violations)


def test_a_removal_is_checked_for_every_eater_not_just_the_baby() -> None:
    """An adult's variant can hallucinate too, and it is the same defect.

    The check is about the DISH, not about who eats it — an aversion variant
    for an adult goes through this same path.
    """
    violations = validate_proposal(
        _plan(serving_variants={"m1": "sans olives"}, variant_removals={"m1": ("Olive",)}),
        SPEC,
        safety=_safety(**WITH_INGREDIENTS),
    )

    assert UNKNOWN_REMOVAL in _codes(violations)
