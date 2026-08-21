"""Fixing what the model MEANT but wrote inconsistently — never what it chose.

Measured on a real Saturday dinner, a household of four with a baby and six
guests. The model emitted, in one answer:

    r_007  eaters=[m1, g1]   variant for m2   <- m2 assigned to nothing
    r_004  eaters=[m3]       variant for m3
    r_004  eaters=[m4]       variant for m4   <- the SAME recipe, written twice

Three attempts, plan rejected, and a household simply forgotten. Both defects
are mechanical: the intent is unambiguous in each case and only the shape is
wrong. Neither repair touches an allergen, a life stage, or which recipe anyone
eats — `validate_proposal` runs afterwards on exactly the same terms.
"""

from __future__ import annotations

from app.domain.enums import MealType
from app.domain.planning import (
    EATER_NOT_SERVED,
    VARIANT_FOR_NON_EATER,
    ProposedDish,
    ProposedSlot,
    SlotSpec,
    repair_shape,
    validate_proposal,
)

SPEC = [SlotSpec(5, MealType.DINNER, ("m1", "m2", "m3", "m4", "g1"))]

#: The answer above, verbatim in shape.
REAL_ANSWER = [
    ProposedSlot(
        5,
        MealType.DINNER,
        (
            ProposedDish(
                eater_aliases=("m1", "g1"),
                recipe_id="r_007",
                serving_variants={"m2": "part prélevée avant salage et mixée"},
            ),
            ProposedDish(
                eater_aliases=("m3",),
                recipe_id="r_004",
                serving_variants={"m3": "coupé en bâtonnets tendres"},
            ),
            ProposedDish(
                eater_aliases=("m4",),
                recipe_id="r_004",
                serving_variants={"m4": "mixé avec un peu d'eau de cuisson"},
            ),
        ),
    )
]


def test_the_real_answer_becomes_valid_without_changing_a_choice() -> None:
    """End to end on the measured failure.

    Nobody is moved to a different recipe: m2 eats what its own variant
    described, m3 and m4 keep r_004. Only the shape changes.
    """
    repaired = repair_shape(REAL_ANSWER)

    assert validate_proposal(repaired, SPEC) == []
    dishes = repaired[0].dishes
    assert len(dishes) == 2, "r_004 was written twice and is one pot"
    assert set(dishes[0].eater_aliases) == {"m1", "g1", "m2"}
    assert set(dishes[1].eater_aliases) == {"m3", "m4"}


def test_the_same_answer_is_rejected_without_the_repair() -> None:
    """The baseline, so this file proves the repair does something."""
    codes = {v.code for v in validate_proposal(REAL_ANSWER, SPEC)}

    assert EATER_NOT_SERVED in codes
    assert VARIANT_FOR_NON_EATER in codes


def test_merging_keeps_every_variant() -> None:
    """Two halves of one pot each carried their own serving instruction.

    Losing one would silently drop a baby's texture — the repair must be
    additive or it is worse than the defect.
    """
    dishes = repair_shape(REAL_ANSWER)[0].dishes

    assert dishes[1].serving_variants == {
        "m3": "coupé en bâtonnets tendres",
        "m4": "mixé avec un peu d'eau de cuisson",
    }


def test_a_stray_variant_on_someone_already_eating_is_left_alone() -> None:
    """That one is a real contradiction, not a slip.

    Someone eating dish A with a variant written on dish B has been described
    twice, and picking a winner would be choosing for the model.
    `VARIANT_FOR_NON_EATER` keeps saying so.
    """
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1", "m2"), recipe_id="r_001"),
                ProposedDish(
                    eater_aliases=("m3",),
                    recipe_id="r_002",
                    serving_variants={"m2": "sans olives"},
                ),
            ),
        )
    ]

    repaired = repair_shape(plan)
    spec = [SlotSpec(5, MealType.DINNER, ("m1", "m2", "m3"))]
    codes = {v.code for v in validate_proposal(repaired, spec)}

    assert VARIANT_FOR_NON_EATER in codes
    assert repaired[0].dishes[1].eater_aliases == ("m3",)


def test_two_different_recipes_are_never_merged() -> None:
    """The merge keys on the recipe id. Different dish, different pot."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1",), recipe_id="r_001"),
                ProposedDish(eater_aliases=("m2",), recipe_id="r_002"),
            ),
        )
    ]

    assert len(repair_shape(plan)[0].dishes) == 2


def test_free_text_dishes_merge_on_their_title() -> None:
    """V0 and the hand-written dish have no recipe id, and the same defect.

    `_dish_identity` already falls back to the label for exactly this.
    """
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1",), label="Gratin"),
                ProposedDish(eater_aliases=("m2",), label="Gratin"),
            ),
        )
    ]

    dishes = repair_shape(plan)[0].dishes
    assert len(dishes) == 1
    assert set(dishes[0].eater_aliases) == {"m1", "m2"}


def test_a_valid_plan_passes_through_untouched() -> None:
    """The repair must be a no-op on what was already right."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (ProposedDish(eater_aliases=("m1", "m2"), recipe_id="r_001"),),
        )
    ]

    assert repair_shape(plan) == plan


def test_the_removals_survive_a_merge() -> None:
    """A removal is safety-adjacent: it says what is not on the plate."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(
                    eater_aliases=("m3",),
                    recipe_id="r_004",
                    serving_variants={"m3": "x"},
                    variant_removals={"m3": ("Noix",)},
                ),
                ProposedDish(
                    eater_aliases=("m4",),
                    recipe_id="r_004",
                    serving_variants={"m4": "y"},
                    variant_removals={"m4": ("Piment",)},
                ),
            ),
        )
    ]

    dishes = repair_shape(plan)[0].dishes
    assert dishes[0].variant_removals == {"m3": ("Noix",), "m4": ("Piment",)}
