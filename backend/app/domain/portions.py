"""Portion scaling.

Deliberately NOT nutrition: no calories, no macronutrients, no daily intakes.
The life stage is the only adequacy proxy, and a per-stage coefficient is all
that is needed to rescale a recipe written "for 4".

Coefficients are configurable (invariant I8); the values below are defaults,
seeded into `portion_coefficient` and overridable per deployment.
"""

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
