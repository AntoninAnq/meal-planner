"""Portion scaling.

Deliberately NOT nutrition: no calories, no macronutrients, no daily intakes.
The life stage is the only adequacy proxy, and a per-stage coefficient is all
that is needed to rescale a recipe written "for 4".

Coefficients are configurable (invariant I8); the values below are defaults,
seeded into `portion_coefficient` and overridable per deployment.
"""

import re
from decimal import Decimal

from app.domain.enums import LifeStage

DEFAULT_PORTION_COEFFICIENTS: dict[LifeStage, Decimal] = {
    LifeStage.BABY: Decimal("0.25"),
    LifeStage.YOUNG_CHILD: Decimal("0.5"),
    LifeStage.TEEN_ADULT: Decimal("1.0"),
}


def total_portions(
    stages: list[LifeStage],
    coefficients: dict[LifeStage, Decimal] | None = None,
) -> Decimal:
    """Portion units needed to feed these members."""
    coeffs = coefficients or DEFAULT_PORTION_COEFFICIENTS
    return sum((coeffs[stage] for stage in stages), start=Decimal(0))


def scale_quantity(
    quantity: Decimal,
    recipe_servings: int,
    eater_stages: list[LifeStage],
    coefficients: dict[LifeStage, Decimal] | None = None,
) -> Decimal:
    """Rescale one ingredient quantity for the members actually eating the dish."""
    if recipe_servings <= 0:
        raise ValueError("recipe_servings must be positive")
    return quantity * total_portions(eater_stages, coefficients) / Decimal(recipe_servings)


#: A `recipeYield` that counts people rather than pieces. Only these are
#: scaled: `Recipe.servings` is the first number the source wrote, and "20
#: tartelettes" is not twenty people. A bare "4" is left alone too — probably
#: four people, but "probably" is not a quantity to buy by. Roughly half of the
#: local catalogue matched when this was measured, on 2026-09-11.
_COUNTS_PEOPLE = re.compile(
    r"\b(?:personnes?|pers\b|parts?|portions?|couverts?|convives?|assiettes?|bols?)\b"
    r"|\bpour\s+\d",
    re.IGNORECASE,
)


def counts_people(servings_raw: str | None) -> bool:
    """Whether the source's yield is a number of people."""
    return bool(servings_raw and _COUNTS_PEOPLE.search(servings_raw))


def scale_factor(
    servings: int | None,
    servings_raw: str | None,
    eater_stages: list[LifeStage],
    coefficients: dict[LifeStage, Decimal] | None = None,
) -> Decimal | None:
    """How much of the recipe this table needs, or None when that cannot be said.

    None — and the source's quantities stand — when the yield is not a number
    of people, when it carries no number, or when nobody eats the dish.
    """
    if not servings or servings <= 0 or not counts_people(servings_raw) or not eater_stages:
        return None
    return total_portions(eater_stages, coefficients) / Decimal(servings)
