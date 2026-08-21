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
    EaterSafety,
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
    repaired = repair_shape(REAL_ANSWER, EaterSafety())

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
    dishes = repair_shape(REAL_ANSWER, EaterSafety())[0].dishes

    assert dishes[1].serving_variants == {
        "m3": "coupé en bâtonnets tendres",
        "m4": "mixé avec un peu d'eau de cuisson",
    }


def test_a_stray_variant_is_dropped_rather_than_left_to_be_rejected() -> None:
    """It describes nothing: there is no plate for it to apply to.

    Someone eating dish A with a variant written on dish B is a real
    contradiction — and adopting them onto B would serve them twice. The
    honest repair is to drop the instruction that applies to no one, NOT to
    change who eats what.

    Leaving it was measured as the worst of both worlds: the plan was rejected,
    and `member_intolerance` reached 2.80 attempts and 78 s before keeping the
    least bad of three degraded tries.
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

    # Nobody moved, and the instruction that applied to no one is gone.
    assert repaired[0].dishes[1].eater_aliases == ("m3",)
    assert repaired[0].dishes[1].serving_variants == {}
    assert validate_proposal(repaired, spec) == []


def test_an_orphan_is_never_adopted_onto_their_allergen() -> None:
    """A repair must never MAKE a plan unsafe.

    Adopting moves someone from "served nothing" — harmless, and caught by
    `EATER_NOT_SERVED` — to "served this dish". Measured when the first version
    adopted unconditionally: `member_intolerance` went from 0 breaches back to
    2 on the harness. Re-validation still caught them, so nothing reached a
    plate, but the retained best attempt held an intolerant eater in front of
    their allergen instead of an unfed one.
    """
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(
                    eater_aliases=("m1",),
                    recipe_id="r_001",
                    serving_variants={"m2": "sans le gratin"},
                ),
            ),
        )
    ]
    safety = EaterSafety(
        allergens_by_recipe={"r_001": frozenset({"milk"})},
        excluded_by_eater={"m2": frozenset({"milk"})},
    )

    unsafe = repair_shape(plan, safety)[0].dishes[0]
    assert unsafe.eater_aliases == ("m1",)
    # …and the instruction that could not be honoured is not left behind.
    assert unsafe.serving_variants == {}
    # Without the allergen, the same orphan IS adopted and keeps their variant.
    safe = repair_shape(plan, EaterSafety())[0].dishes[0]
    assert safe.eater_aliases == ("m1", "m2")
    assert safe.serving_variants == {"m2": "sans le gratin"}


def test_an_orphan_is_not_adopted_onto_a_dish_wrong_for_their_stage() -> None:
    """Same rule, the other half of `_check_eaters_can_eat`."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(
                    eater_aliases=("m1",),
                    recipe_id="r_001",
                    serving_variants={"m3": "sans épices"},
                ),
            ),
        )
    ]
    safety = EaterSafety(
        stages_by_recipe={"r_001": frozenset({"teen_adult"})},
        stage_by_eater={"m3": "young_child"},
    )

    assert repair_shape(plan, safety)[0].dishes[0].eater_aliases == ("m1",)


def test_a_baby_orphan_is_adopted_because_the_variant_opens_it() -> None:
    """§4.9 applies here too: the variant that orphaned them is what allows it.

    Refusing would make the baby unservable by the very mechanism written to
    serve them.
    """
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(
                    eater_aliases=("m1",),
                    recipe_id="r_001",
                    serving_variants={"m4": "part prélevée avant salage, écrasée"},
                ),
            ),
        )
    ]
    safety = EaterSafety(
        stages_by_recipe={"r_001": frozenset({"teen_adult"})},
        stage_by_eater={"m4": "baby"},
    )

    assert repair_shape(plan, safety)[0].dishes[0].eater_aliases == ("m1", "m4")


def test_without_safety_a_catalogue_dish_is_left_alone() -> None:
    """No data, no repair. Guessing is what this whole file exists to avoid."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(
                    eater_aliases=("m1",),
                    recipe_id="r_001",
                    serving_variants={"m2": "x"},
                ),
            ),
        )
    ]

    assert repair_shape(plan)[0].dishes[0].eater_aliases == ("m1",)


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


# ---------------------------------------------------------------------------
# The only repair that undoes a CHOICE
# ---------------------------------------------------------------------------


def test_an_eater_left_alone_for_no_reason_is_brought_back() -> None:
    """The real Saturday dinner that motivated this.

    Six-year-old Joséphine was put alone on a risotto while the household ate
    a leek purée she could perfectly well eat — a second pot for nothing, which
    is exactly what §2.3 makes the objective function refuse.
    """
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1", "m2"), recipe_id="r_001"),
                ProposedDish(eater_aliases=("m3",), recipe_id="r_002"),
            ),
        )
    ]

    dishes = repair_shape(plan, EaterSafety())[0].dishes

    assert len(dishes) == 1
    assert set(dishes[0].eater_aliases) == {"m1", "m2", "m3"}


def test_a_variant_means_the_separation_was_deliberate() -> None:
    """A baby's own plate is described by its serving instruction.

    Moving them would throw the instruction away — and it is the only thing
    saying how that plate is made edible.
    """
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1", "m2"), recipe_id="r_001"),
                ProposedDish(
                    eater_aliases=("m4",),
                    recipe_id="r_002",
                    serving_variants={"m4": "mixé avec un peu d'eau de cuisson"},
                ),
            ),
        )
    ]

    assert len(repair_shape(plan, EaterSafety())[0].dishes) == 2


def test_nobody_is_moved_onto_a_dish_they_cannot_eat() -> None:
    """The separation was justified, and this is how it stays justified."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1", "m2"), recipe_id="r_001"),
                ProposedDish(eater_aliases=("m3",), recipe_id="r_002"),
            ),
        )
    ]
    safety = EaterSafety(
        allergens_by_recipe={"r_001": frozenset({"gluten"})},
        excluded_by_eater={"m3": frozenset({"gluten"})},
    )

    assert len(repair_shape(plan, safety)[0].dishes) == 2


def test_a_pair_sharing_a_second_dish_is_left_alone() -> None:
    """Two people on a dish are a group the model formed on purpose.

    Undoing that would be rewriting the plan, not trimming it.
    """
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1", "m2"), recipe_id="r_001"),
                ProposedDish(eater_aliases=("m3", "m4"), recipe_id="r_002"),
            ),
        )
    ]

    assert len(repair_shape(plan, EaterSafety())[0].dishes) == 2


def test_a_lone_eater_joins_the_biggest_table() -> None:
    """Not another lone diner: the point is fewer preparations."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1",), recipe_id="r_001"),
                ProposedDish(eater_aliases=("m2", "m3", "m4"), recipe_id="r_002"),
            ),
        )
    ]

    dishes = repair_shape(plan, EaterSafety())[0].dishes

    assert len(dishes) == 1
    assert set(dishes[0].eater_aliases) == {"m1", "m2", "m3", "m4"}


def test_a_single_dish_slot_is_never_emptied() -> None:
    """One eater, one dish: there is nowhere to bring them back to."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (ProposedDish(eater_aliases=("m1",), recipe_id="r_001"),),
        )
    ]

    assert repair_shape(plan, EaterSafety()) == plan


def test_without_safety_no_choice_is_undone() -> None:
    """No way to check edibility, no business rewriting the plan."""
    plan = [
        ProposedSlot(
            5,
            MealType.DINNER,
            (
                ProposedDish(eater_aliases=("m1", "m2"), recipe_id="r_001"),
                ProposedDish(eater_aliases=("m3",), recipe_id="r_002"),
            ),
        )
    ]

    assert len(repair_shape(plan)[0].dishes) == 2
